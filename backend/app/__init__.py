"""Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from flask_cors import CORS

from app.api import register_blueprints
from app.api.errors import register_error_handlers
from app.config import Config
from app.extensions import db


def create_app(config: Config | None = None, *, initialize_database: bool = True) -> Flask:
    app = Flask(__name__)
    cfg = config or Config()
    app.config.update(cfg.as_flask_mapping())

    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["FRONTEND_ORIGIN"]}})

    # Import models for metadata. Normal startup uses the explicit Alembic schema;
    # tests may opt into create_all for an isolated in-memory database.
    from app import models  # noqa: F401

    if initialize_database and app.config["AUTO_CREATE_SCHEMA"]:
        with app.app_context():
            db.create_all()

    register_error_handlers(app)
    register_blueprints(app)
    from app.auth import register_auth
    register_auth(app)

    @app.get("/")
    def index():
        return jsonify({
            "name": "ValoreaX API",
            "version": "v1",
            "docs": "/api/v1/meta",
            "disclaimer": "Educational research tool — not investment advice.",
        })

    return app
