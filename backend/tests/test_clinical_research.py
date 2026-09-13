import json

from app.extensions import db
from app.models import Company, RawProviderResponse
from app.providers.clinicaltrials import _map_study
from app.services.llm_clinical import clinical_evidence_for


def test_registry_keeps_design_and_results():
    study = {'protocolSection': {'identificationModule': {'nctId': 'NCT12345678'},
             'designModule': {'enrollmentInfo': {'count': 120}},
             'statusModule': {'primaryCompletionDateStruct': {'date': '2026-01-01'}}},
             'resultsSection': {'outcomeMeasuresModule': {'outcomeMeasures': []}}, 'hasResults': True}
    record = _map_study(study)
    assert record.extra['study_evidence']['resultsSection'] == study['resultsSection']
    assert record.outcome == 'pending'


def test_clinical_scope_cache_and_auth(app, client, monkeypatch):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    app.config['GEMINI_API_KEY'] = 'test-key'
    calls = []

    def generate(config, evidence, question=''):
        calls.append(evidence)
        return {'summary': 'No posted results available.', 'outlook': 'insufficient_data',
                'drivers': [], 'risks': [], 'tensions': [], 'limitations': ['Registry milestones are not results.']}

    monkeypatch.setattr('app.api.v1.research.generate_clinical_research', generate)
    url = '/api/v1/companies/VALX/research'
    assert client.post(url, json={'scope': 'clinical'}).status_code == 200
    assert client.post(url, json={'scope': 'clinical'}).json['cached'] is True
    assert len(calls) == 1
    assert client.post(url, json={'scope': 'invalid'}).status_code == 422
    assert app.test_client().post(url, json={'scope': 'clinical'}).status_code == 401


def test_evidence_excludes_notes_and_bounds_results(app, client):
    client.post('/api/v1/companies', json={'ticker': 'VALX'})
    with app.app_context():
        company = db.session.query(Company).filter_by(ticker='VALX').one()
        payload = {'records': [{'drug_program': 'Test', 'notes': 'PRIVATE NOTE', 'outcome': 'positive',
                   'extra': {'nct_id': 'NCT12345678', 'study_evidence': {
                       'protocolSection': {}, 'resultsSection': {'large': 'x' * 100000}}}}]}
        db.session.add(RawProviderResponse(provider='clinicaltrials', resource_type='clinical_trials',
            resource_key=f'clinicaltrials:{company.cik or company.ticker}', payload=json.dumps(payload)))
        db.session.commit()
        evidence = clinical_evidence_for(db.session, company)
        assert len(json.dumps(evidence)) < 5000
        assert 'PRIVATE NOTE' not in json.dumps(evidence)
        assert evidence[1]['data']['results_available_in_evidence'] is False
        assert 'results_omitted' in evidence[1]['data']['study']


def test_no_results_cannot_receive_positive_outlook(monkeypatch):
    from app.providers.gemini import generate_clinical_research
    monkeypatch.setattr('app.providers.gemini._generate', lambda *args: {
        'outlook': 'positive', 'limitations': []})
    result = generate_clinical_research({}, [{'data': {'results_available_in_evidence': False}}])
    assert result['outlook'] == 'insufficient_data'
    assert 'unassessed' in result['limitations'][0]
