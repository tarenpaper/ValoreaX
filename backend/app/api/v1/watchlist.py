"""Watchlist endpoint: one aggregated row per tracked company."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify

from app.extensions import db
from app.services.watchlist import build_watchlist

bp = Blueprint("watchlist", __name__)


@bp.get("/watchlist")
def get_watchlist():
    rows = build_watchlist(db.session)
    return jsonify({
        "count": len(rows),
        "as_of": date.today().isoformat(),
        "companies": rows,
        "disclaimer": "Educational research — not investment advice. Prices/status may be sample data.",
    })
