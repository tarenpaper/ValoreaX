"""Consistent error responses across the API.

Every error is returned as::

    {"error": {"code": "<slug>", "message": "<human text>", "details": {...}}}

with an appropriate HTTP status code.
"""
from __future__ import annotations

import logging

from flask import jsonify
from marshmallow import ValidationError
from werkzeug.exceptions import HTTPException

from app.providers.base import ProviderError

log = logging.getLogger("valorea.api")


class ApiError(Exception):
    """Raise anywhere in a request to short-circuit with a clean JSON error."""

    def __init__(self, message: str, status: int = 400, code: str | None = None,
                 details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or _code_for_status(status)
        self.details = details or {}


def _code_for_status(status: int) -> str:
    return {
        400: "bad_request", 401: "unauthorized", 403: "forbidden",
        404: "not_found", 405: "method_not_allowed", 409: "conflict",
        422: "validation_error", 500: "internal_error", 502: "upstream_error",
    }.get(status, "error")


def _payload(message: str, status: int, code: str, details: dict):
    return jsonify({"error": {"code": code, "message": message, "details": details}}), status


def register_error_handlers(app) -> None:
    @app.errorhandler(ProviderError)
    def _handle_provider_error(exc: ProviderError):
        return _payload(str(exc), 502, "upstream_error", {})

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return _payload(exc.message, exc.status, exc.code, exc.details)

    @app.errorhandler(ValidationError)
    def _handle_validation(exc: ValidationError):
        return _payload("Request validation failed.", 422, "validation_error", exc.messages)

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        return _payload(exc.description or exc.name, exc.code or 500,
                        _code_for_status(exc.code or 500), {})

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):  # pragma: no cover - safety net
        log.exception("Unhandled error: %s", exc)
        return _payload("An unexpected error occurred.", 500, "internal_error", {})
