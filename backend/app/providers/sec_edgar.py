"""Live SEC EDGAR adapter — free, no API key required.

Uses two public endpoints (a descriptive User-Agent with contact info is required
by SEC's fair-access policy):

* ``/files/company_tickers.json``          — ticker → CIK resolution
* ``/submissions/CIK##########.json``      — company profile (name, SIC, exchange)
* ``/api/xbrl/companyfacts/CIK##########.json`` — the XBRL company facts payload

The ticker map is cached in-process; the (large) company-facts payload is cached
by the ingestion service via CacheService (see docs/CACHING.md).
"""
from __future__ import annotations

import time

import requests

from .base import CompanyNotFound, CompanyProfile, ProviderError, RawResponse, SecDataProvider

# Coarse SIC-prefix → sector buckets, enough to label healthcare names sensibly.
_SIC_SECTOR = {
    "28": "Healthcare",   # chemicals / pharmaceutical preparations
    "38": "Healthcare",   # medical instruments & devices
    "80": "Healthcare",   # health services
    "87": "Healthcare",   # research / testing labs
}


def _sector_from_sic(sic: str | None) -> str | None:
    if not sic:
        return None
    return _SIC_SECTOR.get(str(sic)[:2])


class SecEdgarProvider(SecDataProvider):
    """Adapter over the public SEC EDGAR REST endpoints."""

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str,
        base_url: str = "https://data.sec.gov",
        www_url: str = "https://www.sec.gov",
        timeout: int = 20,
        ticker_map_ttl: int = 86_400,
    ) -> None:
        if not user_agent or "example.com" in user_agent:
            # SEC blocks generic/empty User-Agents; surface this early and clearly.
            raise ProviderError(
                "SEC_USER_AGENT must be set to a descriptive value containing real "
                "contact info (e.g. 'ValoreaX-Research you@domain.com')."
            )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._base_url = base_url.rstrip("/")
        self._www_url = www_url.rstrip("/")
        self._timeout = timeout
        self._ticker_map_ttl = ticker_map_ttl
        self._ticker_map: dict[str, dict] | None = None
        self._ticker_map_fetched_at: float = 0.0

    # --- HTTP helpers ------------------------------------------------------
    def _get_json(self, url: str) -> dict:
        try:
            resp = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"SEC request failed: {exc}") from exc
        if resp.status_code == 404:
            raise CompanyNotFound(f"SEC returned 404 for {url}")
        if resp.status_code != 200:
            raise ProviderError(f"SEC returned HTTP {resp.status_code} for {url}")
        try:
            return resp.json()
        except ValueError as exc:  # pragma: no cover
            raise ProviderError(f"SEC returned non-JSON for {url}") from exc

    # --- Ticker → CIK map --------------------------------------------------
    def _load_ticker_map(self) -> dict[str, dict]:
        fresh = self._ticker_map is not None and (
            time.time() - self._ticker_map_fetched_at < self._ticker_map_ttl
        )
        if fresh:
            return self._ticker_map  # type: ignore[return-value]
        data = self._get_json(f"{self._www_url}/files/company_tickers.json")
        mapping: dict[str, dict] = {}
        for row in data.values():
            mapping[str(row["ticker"]).upper()] = {
                "cik": f"{int(row['cik_str']):010d}",
                "title": row.get("title", ""),
            }
        self._ticker_map = mapping
        self._ticker_map_fetched_at = time.time()
        return mapping

    def _resolve_cik(self, ticker: str) -> tuple[str, str]:
        row = self._load_ticker_map().get(ticker.upper())
        if row is None:
            raise CompanyNotFound(f"Ticker {ticker!r} not found in SEC ticker registry.")
        return row["cik"], row["title"]

    # --- Interface ---------------------------------------------------------
    def get_profile(self, ticker: str) -> CompanyProfile:
        cik, title = self._resolve_cik(ticker)
        try:
            sub = self._get_json(f"{self._base_url}/submissions/CIK{cik}.json")
        except CompanyNotFound:
            sub = {}
        exchanges = sub.get("exchanges") or []
        return CompanyProfile(
            ticker=ticker.upper(),
            name=sub.get("name") or title,
            cik=cik,
            sector=_sector_from_sic(sub.get("sic")),
            industry=sub.get("sicDescription"),
            exchange=exchanges[0] if exchanges else None,
        )

    def get_company_facts(self, ticker: str) -> RawResponse:
        cik, _ = self._resolve_cik(ticker)
        payload = self._get_json(f"{self._base_url}/api/xbrl/companyfacts/CIK{cik}.json")
        return RawResponse(
            provider=self.name,
            resource_type="company_facts",
            resource_key=cik,
            payload=payload,
        )
