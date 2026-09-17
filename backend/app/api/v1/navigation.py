"""Refresh the data used by a sidebar destination before reading its view."""
from flask import Blueprint, g, jsonify
from sqlalchemy import select

from app.api.errors import ApiError
from app.api.v1.helpers import get_company_or_404, get_json_body
from app.extensions import db
from app.models import Company
from app.providers import ProviderError
from app.services.navigation_refresh import refresh_source

bp = Blueprint('navigation', __name__)
SOURCES = {
    'dashboard': ('financials', 'prices', 'catalysts', 'analysts'),
    'news': ('prices', 'catalysts', 'news'),
    'watchlist': ('prices', 'catalysts'),
    'backtest': (),  # The chosen historical range is fetched when a simulation is run.
}


@bp.post('/navigation/refresh')
def refresh_navigation():
    body = get_json_body()
    view = body.get('view')
    if not isinstance(view, str) or view not in SOURCES:
        raise ApiError('Unknown sidebar view.', status=422)
    if view == 'watchlist':
        # Only names on the watchlist need a daily price request; unwatched companies
        # keep their stored data and are refreshed when they are opened.
        companies = db.session.execute(
            select(Company).where(Company.owner_id == g.user_id, Company.watched.is_(True))
            .order_by(Company.ticker)
        ).scalars().all()
    elif body.get('ticker'):
        companies = [get_company_or_404(str(body['ticker']))]
    else:
        companies = []
    results, warnings = [], []
    for company in companies:
        for source in SOURCES[view]:
            try:
                results.append(refresh_source(company, source))
            except (ProviderError, ApiError) as exc:
                db.session.rollback()
                warnings.append(f'{company.ticker} {source}: {str(exc)} Stored data is shown where available.')
    return jsonify({'results': results, 'warnings': warnings, 'cache_seconds': 300})
