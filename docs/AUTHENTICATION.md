# Personal accounts

ValoreaX uses Supabase Auth for email/password signup, confirmation, login, password
recovery, session refresh, and logout. Passwords go directly to Supabase; Flask never
receives or stores them. The React app sends an access token to Flask in the
Authorization header. Flask independently verifies the signature, issuer, audience,
expiry, user UUID, and authenticated role. Anonymous Supabase accounts are rejected.

## Connect your Supabase project

1. Create a Supabase project and enable the email/password provider. Enable email
   confirmation, disable anonymous sign-ins, and set minimum password length to 12.
2. Use an asymmetric JWT signing key (ES256 or RS256). The backend intentionally
   does not accept legacy HS256 secrets or service-role tokens.
3. Set the Site URL to `http://localhost:5173` for development. Allow these redirect
   URLs: `http://localhost:5173/` and `http://localhost:5173/?auth=recovery`.
   Before launch, set the Site URL to the real production frontend and add its
   equivalent two URLs. Avoid wildcard preview domains for production auth.
4. Copy the project URL into `SUPABASE_URL` in `backend/.env` and
   `VITE_SUPABASE_URL` in `frontend/.env`. Copy the public publishable key into
   `VITE_SUPABASE_PUBLISHABLE_KEY`. A legacy anon key also works as the browser key,
   but token signing must still be asymmetric. Never use a service-role key,
   Supabase secret key, or database password in frontend variables.
5. Configure custom SMTP for real users; Supabase's default email delivery is
   intended for development and restricts recipients. Configure Supabase's auth
   rate limits. CAPTCHA is a follow-up for public signup: integrate its browser
   widget/token before enabling it in Supabase.

Official references: [password auth](https://supabase.com/docs/guides/auth/passwords),
[signing keys](https://supabase.com/docs/guides/auth/signing-keys),
[SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

The client uses PKCE. Confirmation/recovery links should be opened in the browser
where the request originated. If a link expires, request a new one. Signed-in users
are sent directly to their workspace; recovery links open the new-password form.
Sign out clears this browser's session and unmounts account-specific UI state.

## Database setup

Install `backend/requirements.txt` into a virtual environment. From `backend/`:

```sh
# NEW database:
alembic upgrade head
python wsgi.py
```

For an EXISTING database made by the previous `db.create_all()` version, back it up
first. Confirm it matches the initial schema, then adopt the baseline and migrate:

```sh
alembic stamp 0001_initial
alembic upgrade head
```

Do not stamp a new/empty database: stamping records a version without creating
tables. Both commands load `backend/.env` and use the same SQLite instance path or
`DATABASE_URL` as the app. Schema changes run explicitly, not in request handlers.
Docker Compose upgrades a new/versioned database before starting Gunicorn; an old
unversioned Docker database needs the baseline adoption step first.

Each company now has an `owner_id` (verified Supabase user UUID) and a unique
`(owner_id, ticker)` pair. All company children—filings, metrics, catalysts, prices,
news, analyst coverage, and signal runs—belong to that account's company tree.
The API scopes numeric IDs, tickers, watchlists, and sector summaries to the user.
Existing rows are preserved with NULL ownership and remain inaccessible from the
API. New accounts start empty and can add a ticker to begin research.

To move legacy research to a specific account, an administrator must explicitly
assign the corresponding companies to that account's Supabase UUID after checking
for ticker conflicts. Nothing is automatically given to the first person to sign up.
The legacy CLI seed still creates unassigned sample data, not an account workspace.

Raw public provider responses, their cache, and benchmark prices are shared server
infrastructure. No API exposes raw cache contents. Manual notes and research results
are account-scoped. This is application-layer isolation; don't expose these tables
directly through a public Supabase data API without separate RLS policies.

## Vercel frontend

The repo now includes `frontend/vercel.json`. Use Node 22 or newer and **frontend** as the Vercel project's
Root Directory and supply all three `VITE_*` values at build time. Rebuild after
changing them. Point `VITE_API_BASE_URL` at the deployed HTTPS Flask API plus `/api/v1`.
Set Flask's `FRONTEND_ORIGIN` to the exact deployed frontend origin.

The Flask backend still needs deployment and a persistent PostgreSQL database;
deploying the Vite frontend alone does not deploy Flask. SQLite on an ephemeral
serverless filesystem is not a hosted database. No deployment is performed by this
change, and the provider defaults remain mock/manual until separately configured.

## Security behavior and validation

- Missing configuration fails closed; there is no auth bypass environment switch.
- Only `/api/v1/health` is public. Metadata and research APIs require a bearer token.
- Protected responses use `Cache-Control: private, no-store` and `Vary: Authorization`.
- JWT key discovery is cached. Invalid tokens return 401; key-discovery outages
  return 503 rather than accepting unverified claims.
- Local logout removes the browser session. An already issued access token can
  remain valid until its expiry, as with normal JWT verification. Configure a short
  access-token lifetime in Supabase; immediate server-side revocation is not implemented.
- Sessions are persisted by the Supabase browser SDK. Maintain XSS protections;
  the frontend must never render untrusted HTML. An HttpOnly-cookie/BFF architecture
  would be a separate deployment design.

Run `pytest` and `ruff check app tests wsgi.py` in `backend/`, then `npm run build`
in `frontend/`. Auth tests use real locally signed ES256 tokens with only remote key
discovery substituted. They cover invalid/expired tokens, missing configuration,
auth-provider outages, CORS, every protected route, and cross-account reads/writes.
Complete a live signup → confirmation → login → logout → recovery test once the
Supabase project and email delivery are configured.
