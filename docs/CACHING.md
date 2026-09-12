# Caching strategy

Implemented by `app/services/cache_service.py` (`CacheService`), persisted in the
`cache_entries` table so the cache survives restarts and is shared across workers.

## Key space

Entries are keyed by `(namespace, key)`:

| namespace        | key            | what it stores                     | typical TTL |
| ---------------- | -------------- | ---------------------------------- | ----------- |
| `company_facts`  | CIK (or ticker)| raw SEC Company-Facts JSON payload | 24 h        |
| `market_price`   | ticker         | (reserved) price series            | 15 min      |

TTLs come from environment variables:

- `CACHE_TTL_COMPANY_FACTS` (default `86400` = 24 h) — filings/profile data changes rarely.
- `CACHE_TTL_MARKET_PRICE` (default `900` = 15 min) — reserved for time-sensitive prices.

## Semantics

- **Write:** `set(ns, key, value, ttl)` stores JSON text with
  `expires_at = now + ttl` (or `NULL` for "never expires").
- **Read:** `get(ns, key)` returns the value, or `None` if absent **or past `expires_at`**
  (lazy expiry — an expired row is deleted on read).
- **Read-through:** `get_or_set(ns, key, ttl, loader)` calls `loader()` only on a miss and
  returns `(value, was_cached)`.
- **SQLite note:** SQLite drops timezone info on read, so timestamps are normalized to aware
  UTC before comparison.

## Invalidation

1. **TTL expiry** — the default path (lazy on read).
2. **Explicit single-key** — `invalidate(ns, key)`. Used by
   `POST /companies/{id}/refresh`, which drops the cached facts before re-ingesting so a
   refresh always hits the live source.
3. **Namespace flush** — `invalidate(ns)` clears an entire namespace.
4. **Sweep** — `purge_expired()` bulk-deletes expired rows (call from a future cron/maintenance
   task).

## Why DB-backed (not in-memory)?

- Survives process restarts and is shared across gunicorn workers / the Vite-independent CLI
  (`python -m app.seed`).
- Raw payloads are large (SEC Company-Facts can be several MB); persisting once avoids
  re-downloading and respects SEC's fair-access policy.
- Trivially inspectable (`SELECT * FROM cache_entries`) for debugging.

### Sidebar navigation

Every sidebar navigation (including reselecting the current tab or ticker) calls
`POST /api/v1/navigation/refresh` before loading the view. Dashboard refreshes
financials, prices, catalysts and analysts; News refreshes prices, catalysts and
news; Watchlist refreshes prices and catalysts for the signed-in account's companies.
Successful source refreshes are cached for 300 seconds. Recent price payloads are
shared by provider, symbol and lookback so the benchmark is not fetched separately
for each watchlist row. Cache hits do not restart the five-minute clock.
Provider errors preserve stored data and appear as warnings; failed refreshes are
not marked successful. This is click-driven, with no background polling. Prices
remain the provider's daily closes, not streaming quotes.

Backtest retains its form across navigation and reruns an existing simulation when
reopened. Historical provider responses are also cached for five minutes. User
investment amounts are not stored in the shared provider cache.
