"""Plutus retrospective explanation of a completed simulation."""
import json
from datetime import date, timedelta

import pytest

from app.providers.base import PricePoint, ProviderError
from app.services.investment_backtest import simulate
from app.services.llm_backtest import (
    CURVE_SAMPLES,
    assess,
    backtest_evidence,
    inflection_points,
    news_evidence_ids,
    news_windows,
    validate_backtest_result,
)


def points(values, start=date(2020, 1, 6)):
    return [PricePoint(date=start + timedelta(days=i), close=v) for i, v in enumerate(values)]


def sample_result(n=400):
    prices = points([100 + (i % 40) for i in range(n)])
    bench = points([100 + (i % 20) for i in range(n)])
    return simulate(prices, bench, prices[0].date, prices[-1].date, 1000)


WINDOW = ('2020-01-06', '2021-02-08')


def output():
    return {'summary': 'The position trailed the benchmark.',
            'observations': [{'text': 'Excess return was negative.', 'evidence_ids': ['E1']}],
            'cautions': [{'text': 'Dividends are excluded.', 'evidence_ids': ['E6']}],
            'tensions': [],
            'context': [{'text': 'A widely reported sector selloff.',
                         'approximate_date': '2020-03', 'confidence': 'medium'}],
            'limitations': ['Price data only.']}


def test_assessment_is_deterministic_not_model_supplied():
    assert assess(0.05) == 'outperformed'
    assert assess(-0.05) == 'underperformed'
    assert assess(0.001) == 'in_line'


def test_evidence_is_bounded_and_price_only():
    result = sample_result()
    evidence = backtest_evidence(result, 'VALX', 'XLV')
    labels = {e['label']: e['data'] for e in evidence}

    assert len(result['curve']) > CURVE_SAMPLES  # the raw curve is long...
    curve = next(v for k, v in labels.items() if k.startswith('Equity curve'))
    assert len(curve['rows']) <= CURVE_SAMPLES  # ...but the snapshot stays bounded

    summary = labels['Simulation result']
    assert summary['assessment_vs_benchmark'] in ('outperformed', 'underperformed', 'in_line')
    assert summary['excess_return'] == result['excess_return']

    # Only price-derived records are supplied; no fundamentals, catalysts or news.
    # (The methodology record is excluded: its disclaimers legitimately name the
    # things the evidence does NOT contain.)
    assert {e['label'] for e in evidence} == {
        'Simulation result', 'Trend label at entry (mechanical, price-only)',
        'Trend label at exit (mechanical, price-only)', 'Equity curve samples',
        'Deepest drawdown session', 'Detected inflection points',
        'Methodology and exclusions'}
    data_blob = json.dumps([e for e in evidence
                            if e['label'] != 'Methodology and exclusions']).lower()
    for forbidden in ('catalyst', 'analyst', 'pdufa', 'revenue', 'ebitda', 'headline'):
        assert forbidden not in data_blob


def test_validation_matches_research_strictness():
    evidence = [{'id': 'E1'}, {'id': 'E6'}]
    assert validate_backtest_result(json.dumps(output()), evidence, WINDOW)['observations']

    unknown = output()
    unknown['observations'] = [{'text': 'x', 'evidence_ids': ['E99']}]
    uncited = output()
    uncited['cautions'] = [{'text': 'x', 'evidence_ids': []}]
    too_many = output()
    too_many['tensions'] = [{'text': 'x', 'evidence_ids': ['E1']}] * 5
    missing = output()
    del missing['observations']
    for bad in (unknown, uncited, too_many, missing):
        with pytest.raises(ProviderError):
            validate_backtest_result(json.dumps(bad), evidence, WINDOW)


def test_context_must_be_dated_inside_the_window_and_graded():
    evidence = [{'id': 'E1'}, {'id': 'E6'}]
    ok = validate_backtest_result(json.dumps(output()), evidence, WINDOW)
    assert ok['context'][0]['confidence'] == 'medium'
    # Uncited causes are allowed but flagged, so the UI can mark them unverified.
    assert ok['context'][0]['evidence_ids'] == []
    assert ok['context'][0]['sourced'] is False

    before = output()
    before['context'][0]['approximate_date'] = '2019-11'      # predates the period
    after = output()
    after['context'][0]['approximate_date'] = '2021-09'       # postdates the period
    graded = output()
    graded['context'][0]['confidence'] = 'certain'            # not an allowed level
    undated = output()
    del undated['context'][0]['approximate_date']
    malformed = output()
    malformed['context'][0]['approximate_date'] = 'early 2020'
    flooded = output()
    flooded['context'] = flooded['context'] * 7               # exceeds MAX_CONTEXT
    for bad in (before, after, graded, undated, malformed, flooded):
        with pytest.raises(ProviderError):
            validate_backtest_result(json.dumps(bad), evidence, WINDOW)

    # An empty list is always valid: omitting beats guessing.
    empty = output()
    empty['context'] = []
    assert validate_backtest_result(json.dumps(empty), evidence, WINDOW)['context'] == []


def test_context_may_only_cite_news_records():
    evidence = [{'id': 'E1'}, {'id': 'E6'}, {'id': 'E7'}]
    news_ids = {'E7'}

    cited = output()
    cited['context'][0]['evidence_ids'] = ['E7']
    result = validate_backtest_result(json.dumps(cited), evidence, WINDOW, news_ids)
    assert result['context'][0]['sourced'] is True

    # Citing a real-but-non-news record would dress a recollection as sourced.
    wrong = output()
    wrong['context'][0]['evidence_ids'] = ['E1']
    unknown = output()
    unknown['context'][0]['evidence_ids'] = ['E99']
    for bad in (wrong, unknown):
        with pytest.raises(ProviderError):
            validate_backtest_result(json.dumps(bad), evidence, WINDOW, news_ids)

    # With no news coverage at all, nothing may be cited.
    with pytest.raises(ProviderError):
        validate_backtest_result(json.dumps(cited), evidence, WINDOW, set())


def test_inflection_points_are_computed_not_chosen():
    # Rise to 150, fall to 75, recover to 130 -> crest, trough, crest.
    def curve(values):
        return [{'date': f'2020-{1 + i // 28:02d}-{1 + i % 28:02d}', 'value': v, 'close': v / 10}
                for i, v in enumerate(values)]

    values = ([100 + i for i in range(51)] + [150 - 1.5 * i for i in range(51)]
              + [75 + 1.1 * i for i in range(51)])
    points = inflection_points(curve(values))
    kinds = [p['kind'] for p in points]
    assert 'trough' in kinds and 'crest' in kinds
    trough = min(points, key=lambda p: p['value'])
    assert trough['kind'] == 'trough'
    assert trough['value'] == pytest.approx(75, abs=2)
    assert all(p['date'] == sorted(q['date'] for q in points)[i] for i, p in enumerate(points))
    # A flat curve has no swings worth narrating.
    assert inflection_points(curve([100] * 60)) == []


def _stub_market(monkeypatch, app):
    """Deterministic 'twelve_data' history so the endpoint can run offline."""
    app.config['MARKET_DATA_PROVIDER'] = 'twelve_data'
    prices = points([100 + (i % 40) for i in range(400)])

    class Provider:
        name = 'twelve_data'

        def get_history(self, symbol, start, end):
            return prices

    monkeypatch.setattr('app.api.v1.backtest.get_market_provider', lambda: Provider())
    return prices


def _request(client, prices, **extra):
    return client.post('/api/v1/companies/VALX/backtest', json={
        'start_date': prices[0].date.isoformat(), 'end_date': prices[-1].date.isoformat(),
        'investment': 1000, **extra})


def test_explanation_is_opt_in_cached_and_never_breaks_the_simulation(app, client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    prices = _stub_market(monkeypatch, app)

    # Opt-in: no explanation unless asked.
    assert 'explanation' not in _request(client, prices).get_json()

    # Without a key the numbers still return, with a setup status.
    app.config['GEMINI_API_KEY'] = ''
    assert _request(client, prices, explain=True).get_json()['explanation']['status'] == 'needs_setup'

    app.config['GEMINI_API_KEY'] = 'test'
    calls = []
    monkeypatch.setattr('app.api.v1.backtest.generate_backtest_explanation',
                        lambda config, evidence, question='', window=None, news_ids=None: calls.append(question) or output())

    first = _request(client, prices, explain=True).get_json()
    assert first['total_return'] is not None                     # simulation intact
    assert first['explanation']['status'] == 'ready'
    assert first['explanation']['cached'] is False
    assert first['explanation']['observations']
    assert _request(client, prices, explain=True).get_json()['explanation']['cached'] is True
    assert len(calls) == 1

    # Distinct questions are cached separately.
    _request(client, prices, explain=True, question='Why the drawdown?')
    assert calls == ['', 'Why the drawdown?']

    # A provider failure degrades to an error status, never a 5xx.
    def boom(config, evidence, question='', window=None, news_ids=None):
        raise ProviderError('Gemini is temporarily unavailable. Please retry.')

    monkeypatch.setattr('app.api.v1.backtest.generate_backtest_explanation', boom)
    failed = _request(client, prices, explain=True, question='another')
    assert failed.status_code == 200
    assert failed.get_json()['explanation']['status'] == 'error'
    assert failed.get_json()['final_value'] is not None


# --- News adapter -----------------------------------------------------------
def test_finnhub_fetch_window_requests_the_historical_range():
    from app.providers.finnhub_news import FinnhubNewsProvider

    provider = FinnhubNewsProvider(api_key='k')
    sent = {}

    class Response:
        status_code = 200

        def json(self):
            return [{'id': 1, 'headline': 'Approval granted', 'source': 'Reuters',
                     'url': 'https://example.com/a', 'datetime': 1609459200,
                     'summary': 'A summary.'}]

    def get(url, params=None, timeout=None):
        sent.update(params)
        return Response()

    provider._session.get = get
    items = provider.fetch_window('pfe', date(2021, 12, 6), date(2021, 12, 18))
    assert provider.supports_history is True
    assert sent['symbol'] == 'PFE'
    assert sent['from'] == '2021-12-06' and sent['to'] == '2021-12-18'
    assert items[0].headline == 'Approval granted'
    assert 'k' == sent['token']


def test_news_windows_reports_coverage_gaps_without_failing(db):
    from app.providers.base import NewsProvider
    from app.services.cache_service import CacheService

    pivots = [{'date': '2021-12-16', 'kind': 'crest', 'change_from_previous_pivot': 0.3},
              {'date': '2022-03-01', 'kind': 'trough', 'change_from_previous_pivot': -0.25}]

    class Empty(NewsProvider):
        name = 'empty'
        supports_history = True

        def fetch(self, ticker, lookback_days=30, max_articles=40):
            return []

        def fetch_window(self, ticker, start, end, max_articles=40):
            return []

    class Broken(Empty):
        name = 'broken'

        def fetch_window(self, ticker, start, end, max_articles=40):
            raise ProviderError('upstream down')

    for provider in (Empty(), Broken()):
        windows = news_windows(provider, CacheService(db.session), 'PFE', pivots)
        assert len(windows) == 2
        assert all(w['articles'] == [] for w in windows)

    # An empty window is a coverage gap, not evidence that nothing happened.
    evidence = backtest_evidence(sample_result(), 'PFE', 'XLV',
                                 news=news_windows(Empty(), CacheService(db.session), 'PFE', pivots))
    gap = next(e for e in evidence if e['label'].startswith('News around'))
    assert 'absence is not evidence' in gap['data']['coverage']
    assert news_evidence_ids(evidence) == {e['id'] for e in evidence
                                           if e['label'].startswith('News around')}
