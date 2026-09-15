"""Server-only Gemini generateContent adapter; no tools or external browsing."""
import json
import re

import requests

from app.providers.base import ProviderError
from app.services.llm_backtest import BACKTEST_PROMPT, validate_backtest_result
from app.services.llm_clinical import CLINICAL_PROMPT
from app.services.llm_filing import (
    BUSINESS_PROMPT,
    EXCLUSIVITY_PROMPT,
    GEOGRAPHIES,
    PHASES,
    PROTECTIONS,
    TERRITORIES,
    validate_business,
    validate_exclusivity,
)
from app.services.llm_research import PROMPT, validate_result

# finishReason values meaning a safety/policy filter stopped the answer, not a fault.
BLOCKED_FINISH_REASONS = {'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII',
                          'RECITATION', 'IMAGE_SAFETY'}

_POINT = {'type': 'object', 'properties': {'text': {'type': 'string'},
          'evidence_ids': {'type': 'array', 'items': {'type': 'string'}}},
          'required': ['text', 'evidence_ids']}


def _schema(fields, extra_properties=None):
    """Structured-output schema: a summary, cited point lists, and string limitations."""
    properties = {'summary': {'type': 'string'},
                  **(extra_properties or {}),
                  **{name: {'type': 'array', 'items': _POINT} for name in fields},
                  'limitations': {'type': 'array', 'items': {'type': 'string'}}}
    return {'type': 'object', 'properties': properties, 'required': list(properties)}


RESEARCH_SCHEMA = _schema(
    ('drivers', 'risks', 'tensions'),
    {'outlook': {'type': 'string',
                 'enum': ['positive', 'mixed', 'negative', 'insufficient_data']}})

# Causes cite news records when coverage exists; otherwise evidence_ids is empty and
# the entry is rendered as unverified recollection.
_CONTEXT_ITEM = {'type': 'object', 'properties': {
    'text': {'type': 'string'}, 'approximate_date': {'type': 'string'},
    'confidence': {'type': 'string', 'enum': ['high', 'medium', 'low']},
    'evidence_ids': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['text', 'approximate_date', 'confidence', 'evidence_ids']}

BACKTEST_SCHEMA = _schema(('observations', 'cautions', 'tensions'),
                          {'context': {'type': 'array', 'items': _CONTEXT_ITEM}})

_STRING = {'type': 'string'}
_CITED = {'evidence_id': _STRING, 'quote': _STRING}


def _items(properties, required):
    return {'type': 'array', 'items': {'type': 'object', 'properties': properties, 'required': required}}


# Filing extraction: every item cites an excerpt and quotes it (see llm_filing.py).
BUSINESS_SCHEMA = {'type': 'object', 'properties': {
    'pipeline': _items({'name': _STRING, 'aliases': {'type': 'array', 'items': _STRING},
                        'indication': _STRING, 'phase': {'type': 'string', 'enum': list(PHASES)},
                        'milestone': _STRING, **_CITED},
                       ['name', 'phase', 'evidence_id', 'quote']),
    'marketed': _items({'name': _STRING, 'indication': _STRING, **_CITED},
                       ['name', 'evidence_id', 'quote']),
    'populations': _items({'indication': _STRING, 'patients': {'type': 'number'},
                           'geography': {'type': 'string', 'enum': list(GEOGRAPHIES)}, **_CITED},
                          ['indication', 'patients', 'geography', 'evidence_id', 'quote'])},
    'required': ['pipeline', 'marketed', 'populations']}

EXCLUSIVITY_SCHEMA = {'type': 'object', 'properties': {
    'rows': _items({'product': _STRING, 'protection': {'type': 'string', 'enum': list(PROTECTIONS)},
                    'territory': {'type': 'string', 'enum': list(TERRITORIES)},
                    'expiry_year': {'type': 'integer'}, **_CITED},
                   ['product', 'protection', 'territory', 'expiry_year', 'evidence_id', 'quote']),
    'caveats': _items({'text': _STRING, **_CITED}, ['text', 'evidence_id', 'quote'])},
    'required': ['rows', 'caveats']}


def _answer_text(body):
    """Extract the answer from a generateContent body, or raise a specific ProviderError.

    Kept outside the network try/except so a blocked, empty or truncated response is
    never reported as a transport failure.
    """
    if not isinstance(body, dict):
        raise ProviderError('Gemini returned an unreadable response. Please retry.')
    blocked = (body.get('promptFeedback') or {}).get('blockReason')
    if blocked:
        raise ProviderError(f'Gemini blocked this request ({blocked}). '
                            'Adjust the question or evidence and retry.')
    candidates = body.get('candidates')
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError('Gemini returned no analysis for this request. Please retry.')
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    reason = candidate.get('finishReason')
    if reason in BLOCKED_FINISH_REASONS:
        raise ProviderError(f'Gemini stopped this analysis for policy reasons ({reason}). '
                            'Adjust the question or evidence and retry.')
    if reason == 'MAX_TOKENS':
        raise ProviderError('Gemini ran out of output space before finishing. Please retry.')
    if reason != 'STOP':
        raise ProviderError('Gemini did not complete this analysis. Please retry.')
    parts = (candidate.get('content') or {}).get('parts') or []
    # Drop Gemini's internal reasoning parts; only the answer text reaches the client.
    return ''.join(p.get('text', '') for p in parts if isinstance(p, dict) and not p.get('thought'))


def _generate(config, prompt, schema, validator, evidence, question, max_output_tokens=8192,
              read_timeout=60):
    key = config.get('GEMINI_API_KEY', '').strip()
    model = config.get('GEMINI_MODEL', 'gemini-3.6-flash')
    if not key:
        raise ProviderError('Gemini is not configured. Add GEMINI_API_KEY to the backend environment.')
    if not re.fullmatch(r'gemini-[a-zA-Z0-9.-]+', model):
        raise ProviderError('GEMINI_MODEL must be a Gemini model identifier.')
    try:
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
            json={'systemInstruction': {'parts': [{'text': prompt}]},
                  'contents': [{'role': 'user', 'parts': [{'text': json.dumps({'evidence': evidence, 'question': question})}]}],
                  'generationConfig': {'responseMimeType': 'application/json',
                                       'responseJsonSchema': schema,
                                       'maxOutputTokens': max_output_tokens}},
            timeout=(10, read_timeout))
    except requests.RequestException as exc:
        raise ProviderError('Gemini is temporarily unavailable. Please retry.') from exc
    if response.status_code == 429:
        raise ProviderError('Gemini quota or rate limit reached. Please try again later.')
    if response.status_code in (400, 401, 403, 404):
        raise ProviderError('Gemini rejected the request. Check the backend API key and model access.')
    if response.status_code >= 500:
        raise ProviderError('Gemini is temporarily unavailable. Please retry.')
    if response.status_code != 200:
        raise ProviderError(f'Gemini returned an unexpected response (HTTP {response.status_code}).')
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderError('Gemini returned an unreadable response. Please retry.') from exc
    return validator(_answer_text(body), evidence)


def generate_research(config, evidence, question=""):
    """Company research synthesis grounded in the supplied evidence."""
    return _generate(config, PROMPT, RESEARCH_SCHEMA, validate_result, evidence, question)


def generate_clinical_research(config, evidence, question=""):
    result = _generate(config, CLINICAL_PROMPT, RESEARCH_SCHEMA, validate_result, evidence, question)
    if not any(item.get('data', {}).get('results_available_in_evidence') for item in evidence):
        result['outlook'] = 'insufficient_data'
        result['limitations'] = [
            'No posted clinical results are included in this analysis. Efficacy and safety remain unassessed.',
            *result['limitations'][:4],
        ]
    return result


# Extraction returns many quoted rows, far more output than a research summary, and takes
# correspondingly longer to generate.
FILING_OUTPUT_TOKENS = 32_768
FILING_READ_TIMEOUT = 300


def generate_filing_business(config, evidence):
    """Pipeline programmes, marketed products and patient populations from a 10-K."""
    return _generate(config, BUSINESS_PROMPT, BUSINESS_SCHEMA, validate_business, evidence, "",
                     max_output_tokens=FILING_OUTPUT_TOKENS, read_timeout=FILING_READ_TIMEOUT)


def generate_filing_exclusivity(config, evidence):
    """Patent and exclusivity expiry rows from a 10-K."""
    return _generate(config, EXCLUSIVITY_PROMPT, EXCLUSIVITY_SCHEMA, validate_exclusivity, evidence, "",
                     max_output_tokens=FILING_OUTPUT_TOKENS, read_timeout=FILING_READ_TIMEOUT)


def generate_backtest_explanation(config, evidence, question="", window=None, news_ids=None):
    """Retrospective explanation of a completed simulation (never a forecast).

    `window` is the simulated (entry_date, exit_date): context entries must be dated
    inside it. `news_ids` are the only evidence records a cause may cite.
    """
    def validator(raw, supplied):
        return validate_backtest_result(raw, supplied, window, news_ids)

    return _generate(config, BACKTEST_PROMPT, BACKTEST_SCHEMA, validator, evidence, question)
