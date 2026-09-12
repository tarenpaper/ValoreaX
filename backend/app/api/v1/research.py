"""Account-scoped Gemini research, cached for five minutes per evidence snapshot."""
import hashlib
import json
from threading import RLock

from flask import Blueprint, current_app, g, jsonify, request

from app.api.errors import ApiError
from app.api.schemas import DcfAssumptionsSchema
from app.api.v1.helpers import cache_service, get_company_or_404
from app.extensions import db
from app.models.common import utcnow
from app.providers.gemini import generate_research
from app.services.llm_research import evidence_for

bp = Blueprint('research', __name__)
_lock = RLock()


@bp.post('/companies/<identifier>/research')
def research(identifier):
    company = get_company_or_404(identifier)
    if not current_app.config.get('GEMINI_API_KEY'):
        return jsonify({'status': 'needs_setup', 'message': 'Gemini research is ready to connect.'})
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ApiError('Provide a question object.', status=422)
    question = body.get('question', '')
    if not isinstance(question, str) or len(question) > 1000:
        raise ApiError('Keep your research question under 1,000 characters.', status=422)
    question = question.strip()
    assumptions = body.get('assumptions')
    if assumptions is not None:
        if not isinstance(assumptions, dict):
            raise ApiError('Provide DCF assumptions as an object.', status=422)
        # Validated here, then recomputed server-side; client figures are never trusted.
        assumptions = {k: round(v, 6) if isinstance(v, float) else v
                       for k, v in DcfAssumptionsSchema().load(assumptions).items()}
    evidence = evidence_for(db.session, company, assumptions)
    model = current_app.config['GEMINI_MODEL']
    digest = hashlib.sha256(json.dumps(
        {'evidence': evidence, 'question': question, 'assumptions': assumptions},
        sort_keys=True).encode()).hexdigest()
    # Bump the prompt version whenever PROMPT or the response schema changes.
    key = f'{g.user_id}:{company.id}:{model}:v2:{digest}'
    with _lock:
        def loader():
            return {'status': 'ready', 'ticker': company.ticker, 'model': model,
                    'generated_at': utcnow().isoformat(), 'evidence': evidence,
                    **(generate_research(current_app.config, evidence, question) if question else generate_research(current_app.config, evidence))}
        result, cached = cache_service().get_or_set('gemini_research', key, 300, loader, provider='gemini')
    return jsonify({**result, 'cached': cached})
