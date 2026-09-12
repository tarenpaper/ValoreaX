import json

import pytest

from app.providers import ProviderError
from app.services.llm_research import validate_result


def output():
    return {'summary': 'The available evidence is mixed.', 'outlook': 'mixed',
            'drivers': [{'text': 'Company evidence is available.', 'evidence_ids': ['E1']}],
            'risks': [], 'tensions': [], 'limitations': ['Clinical outcomes remain uncertain.']}


def test_research_setup_auth_cache_and_account_scope(app, client, token_for, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    url = '/api/v1/companies/VALX/research'
    assert client.post(url).json['status'] == 'needs_setup'
    app.config['GEMINI_API_KEY'] = 'test-secret'
    calls = []

    def generate(config, evidence):
        calls.append(evidence)
        assert 'owner_id' not in json.dumps(evidence)
        return output()

    monkeypatch.setattr('app.api.v1.research.generate_research', generate)
    first = client.post(url)
    assert first.status_code == 200 and first.json['cached'] is False
    assert first.json['status'] == 'ready'
    assert client.post(url).json['cached'] is True
    assert len(calls) == 1
    assert 'test-secret' not in first.text
    other = app.test_client()
    assert other.post(url).status_code == 401
    other.environ_base['HTTP_AUTHORIZATION'] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    assert other.post(url).status_code == 404
    assert len(calls) == 1


def test_research_rejects_unknown_evidence_and_malformed_output():
    value = output()
    value['drivers'][0]['evidence_ids'] = ['invented']
    with pytest.raises(ProviderError):
        validate_result(json.dumps(value), [{'id': 'E1'}])
    for raw in ('null', '{}', 'not json'):
        with pytest.raises(ProviderError):
            validate_result(raw, [])


def test_tensions_are_validated_like_drivers():
    value = output()
    value['tensions'] = [{'text': 'The DCF leans on terminal value.', 'evidence_ids': ['E1']}]
    assert validate_result(json.dumps(value), [{'id': 'E1'}])['tensions'] == value['tensions']

    # Hallucinated citations, over-length lists and a missing field are all rejected.
    unknown = output()
    unknown['tensions'] = [{'text': 'Conflict.', 'evidence_ids': ['E9']}]
    too_many = output()
    too_many['tensions'] = [{'text': 'Conflict.', 'evidence_ids': ['E1']}] * 5
    uncited = output()
    uncited['tensions'] = [{'text': 'Conflict.', 'evidence_ids': []}]
    missing = output()
    del missing['tensions']
    for value in (unknown, too_many, uncited, missing):
        with pytest.raises(ProviderError):
            validate_result(json.dumps(value), [{'id': 'E1'}])


def test_gemini_transport_and_truncation(monkeypatch):
    from app.providers.gemini import generate_research
    calls = []

    class Response:
        status_code = 200
        finish = 'STOP'

        def raise_for_status(self):
            pass

        def json(self):
            return {'candidates': [{'finishReason': self.finish, 'content': {'parts': [
                {'thought': True, 'text': 'internal reasoning'}, {'text': json.dumps(output())}]}}]}

    response = Response()

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr('app.providers.gemini.requests.post', post)
    config = {'GEMINI_API_KEY': 'secret', 'GEMINI_MODEL': 'gemini-3.6-flash'}
    assert generate_research(config, [{'id': 'E1'}]) == output()
    assert 'secret' not in calls[0][0]
    assert calls[0][1]['headers']['x-goog-api-key'] == 'secret'
    response.finish = 'MAX_TOKENS'
    with pytest.raises(ProviderError):
        generate_research(config, [{'id': 'E1'}])
    response.status_code = 429
    with pytest.raises(ProviderError, match='quota'):
        generate_research(config, [{'id': 'E1'}])


def _call_gemini(monkeypatch, body=None, status=200, exc=None, unreadable=False):
    """Drive generate_research against a stubbed HTTP response."""

    class Response:
        def json(self):
            if unreadable:
                raise ValueError('not json')
            return body

    Response.status_code = status

    def post(url, **kwargs):
        if exc:
            raise exc
        return Response()

    monkeypatch.setattr('app.providers.gemini.requests.post', post)
    from app.providers.gemini import generate_research
    return generate_research({'GEMINI_API_KEY': 'k', 'GEMINI_MODEL': 'gemini-3.6-flash'}, [{'id': 'E1'}])


def test_blocked_empty_and_unreadable_responses_report_distinctly(monkeypatch):
    """A blocked or empty response must not masquerade as a transport failure."""
    import requests

    cases = {
        'blocked': {'promptFeedback': {'blockReason': 'SAFETY'}},
        'no analysis': {'candidates': []},
        'policy reasons': {'candidates': [{'finishReason': 'PROHIBITED_CONTENT'}]},
        'output space': {'candidates': [{'finishReason': 'MAX_TOKENS'}]},
        'did not complete': {'candidates': [{'finishReason': 'OTHER'}]},
    }
    messages = []
    for fragment, body in cases.items():
        with pytest.raises(ProviderError, match=fragment) as info:
            _call_gemini(monkeypatch, body=body)
        messages.append(str(info.value))

    with pytest.raises(ProviderError, match='unreadable'):
        _call_gemini(monkeypatch, unreadable=True)
    with pytest.raises(ProviderError, match='temporarily unavailable'):
        _call_gemini(monkeypatch, exc=requests.ConnectionError('boom'))
    with pytest.raises(ProviderError, match='temporarily unavailable'):
        _call_gemini(monkeypatch, body={}, status=503)
    with pytest.raises(ProviderError, match='HTTP 302'):
        _call_gemini(monkeypatch, body={}, status=302)

    # Each condition carries its own message rather than one catch-all.
    assert len(set(messages)) == len(cases)
    assert not any('temporarily unavailable' in m for m in messages)


def test_research_questions_are_validated_and_cached_separately(app, client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    app.config['GEMINI_API_KEY'] = 'test'
    calls = []

    def generate(config, evidence, question=''):
        calls.append(question)
        return output()

    monkeypatch.setattr('app.api.v1.research.generate_research', generate)
    url = '/api/v1/companies/VALX/research'
    assert client.post(url, json={'question': 'Assess cash'}).status_code == 200
    assert client.post(url, json={'question': 'Assess cash'}).json['cached'] is True
    assert client.post(url, json={'question': 'Assess risks'}).json['cached'] is False
    assert calls == ['Assess cash', 'Assess risks']
    assert client.post(url, json={'question': 4}).status_code == 422
    assert client.post(url, json={'question': 'x' * 1001}).status_code == 422


ASSUMPTIONS = {'revenue_growth': 0.15, 'operating_margin': 0.15, 'wacc': 0.10,
               'terminal_growth': 0.025}


def test_evidence_includes_signal_and_dcf(app, client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    client.post('/api/v1/companies/VALX/signals', json={'valuation_upside': 0.3,
                                                        'manual_confidence': 0.8})
    app.config['GEMINI_API_KEY'] = 'test'
    seen = []
    monkeypatch.setattr('app.api.v1.research.generate_research',
                        lambda config, evidence, question='': seen.append(evidence) or output())

    url = '/api/v1/companies/VALX/research'
    assert client.post(url, json={'assumptions': ASSUMPTIONS}).status_code == 200
    labels = {record['label']: record['data'] for record in seen[0]}

    signal = labels['Deterministic signal score']
    assert signal['signal'] in ('long', 'short', 'watchlist')
    # Components, not just the verdict, so the model has material to scrutinise.
    assert any(c['name'] == 'valuation_upside' and c['contribution'] for c in signal['components'])

    dcf = labels['Discounted cash flow model']
    assert dcf['assumptions']['wacc'] == 0.10
    assert set(dcf['scenarios']) == {'base', 'bull', 'bear'}
    assert dcf['scenarios']['base']['terminal_value_share_of_ev'] is not None
    assert dcf['inputs']['sources']['base_revenue'] == 'sec'


def test_dcf_evidence_is_optional_and_assumptions_are_validated(app, client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    app.config['GEMINI_API_KEY'] = 'test'
    seen = []
    monkeypatch.setattr('app.api.v1.research.generate_research',
                        lambda config, evidence, question='': seen.append(evidence) or output())

    url = '/api/v1/companies/VALX/research'
    assert client.post(url, json={}).status_code == 200
    assert not any(r['label'] == 'Discounted cash flow model' for r in seen[0])

    # Distinct assumptions must not reuse a cached answer.
    assert client.post(url, json={'assumptions': ASSUMPTIONS}).json['cached'] is False
    assert client.post(url, json={'assumptions': ASSUMPTIONS}).json['cached'] is True
    assert client.post(url, json={'assumptions': {**ASSUMPTIONS, 'wacc': 0.12}}).json['cached'] is False

    for bad in ({'wacc': 0.1}, {**ASSUMPTIONS, 'wacc': 9.0}, 'not-an-object'):
        assert client.post(url, json={'assumptions': bad}).status_code == 422
