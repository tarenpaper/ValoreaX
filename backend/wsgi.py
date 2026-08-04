"""WSGI entrypoint (used by gunicorn and `flask run`)."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # load backend/.env if present (no-op in Docker where env is injected)

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
