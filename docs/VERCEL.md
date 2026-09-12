# Vercel deployment

Import the GitHub repository as two Vercel projects: the Vite frontend with root
directory `frontend`, and the Flask API with root directory `backend`.
The API entrypoint is `wsgi.py`; use Python 3.12 and Node 22 for the frontend.

## Backend environment

Set `DATABASE_URL` to the Supabase PostgreSQL session-pooler URI (port 5432), with
the password URL-encoded. Vercel connections require TLS and use the external
pooler instead of keeping idle database connections in each function instance.
SQLite is rejected on Vercel. Set `AUTO_CREATE_SCHEMA=false`, `FLASK_ENV=production`,
`SUPABASE_URL`, a generated `SECRET_KEY`, and `FRONTEND_ORIGIN` to the exact HTTPS
frontend origin. Configure the provider keys and identifiers from `LIVE_DATA.md`,
including `GEMINI_API_KEY` and `GEMINI_MODEL`, as server-only environment variables.

Run `PGSSLMODE=require .venv/bin/alembic upgrade head` from `backend` with the
production DATABASE_URL loaded before deploying schema-dependent code. Migrations
are explicit, not run during concurrent function startup or preview builds.
Migration 0003 enables row-level security on the application tables. There are no
browser access policies: the backend database owner accesses them and Flask
validates Supabase JWTs and scopes queries to the signed-in account.

## Frontend environment

Set `VITE_API_BASE_URL=https://YOUR-API.vercel.app/api/v1`, `VITE_SUPABASE_URL`, and
`VITE_SUPABASE_PUBLISHABLE_KEY`. These are public build-time values. Never put
database credentials or provider keys in a `VITE_` variable. Rebuild after edits.

Set Supabase Authentication's Site URL to the frontend HTTPS URL, and allow that
origin's login and password-recovery redirect URLs. Preview deployments should use
a separate database and explicit allowed origins rather than production records.

## Verification

Verify the API's `/api/v1/health`, rejection of unauthenticated account requests,
frontend sign-in and sign-out, a watchlist refresh, and Gemini research. Provider
requests are bounded by the API function's 300-second maximum. Existing local
SQLite records are not automatically copied into the production database.
