"""Verify Supabase access tokens before any research API handler executes."""
from __future__ import annotations

from uuid import UUID

import jwt
from flask import g, jsonify, request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError

from app.api.errors import ApiError


class TokenVerifier:
    def __init__(self, url: str):
        self.issuer = f"{url.rstrip('/')}/auth/v1"
        self.keys = PyJWKClient(f"{self.issuer}/.well-known/jwks.json", timeout=5)

    def verify(self, token: str) -> dict:
        # Never select permitted algorithms or a key URL from untrusted claims.
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in {"ES256", "RS256"}:
            raise jwt.InvalidAlgorithmError("An asymmetric Supabase signing key is required.")
        key = self.keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=["ES256", "RS256"],
            issuer=self.issuer, audience="authenticated",
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        UUID(claims["sub"])
        if claims.get("role") != "authenticated" or claims.get("is_anonymous", False):
            raise jwt.InvalidTokenError("A personal account is required.")
        return claims


def register_auth(app):
    url = app.config.get("SUPABASE_URL", "").strip()
    app.extensions["token_verifier"] = TokenVerifier(url) if url else None

    @app.before_request
    def require_account():
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return None
        if request.endpoint == "health.health":
            return None
        authorization = request.headers.get("Authorization", "").split()
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            raise ApiError("Sign in to access your workspace.", status=401)
        verifier = app.extensions["token_verifier"]
        if verifier is None:
            raise ApiError("Authentication is not configured.", status=503, code="auth_unavailable")
        try:
            g.account = verifier.verify(authorization[1])
        except PyJWKClientConnectionError as exc:
            raise ApiError("Authentication is temporarily unavailable. Please retry.",
                           status=503, code="auth_unavailable") from exc
        except (PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise ApiError("Your session is invalid or expired. Please sign in again.",
                           status=401) from exc
        g.user_id = g.account["sub"]
        return None

    @app.after_request
    def private_response(response):
        if request.path.startswith("/api/") and request.endpoint != "health.health":
            response.headers["Cache-Control"] = "private, no-store"
            response.vary.add("Authorization")
        if response.status_code == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.get("/api/v1/auth/me")
    def current_account():
        return jsonify({"id": g.user_id, "email": g.account.get("email")})
