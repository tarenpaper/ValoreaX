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
from concurrent.futures import ThreadPoolExecutor

import requests

from .base import (
    AnnualReport,
    CompanyNotFound,
    CompanyProfile,
    ProviderError,
    RawResponse,
    SecDataProvider,
)

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
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._base_url = base_url.rstrip("/")
        self._www_url = www_url.rstrip("/")
        self._timeout = timeout
        self._ticker_map_ttl = ticker_map_ttl
        self._ticker_map: dict[str, dict] | None = None
        self._ticker_map_fetched_at: float = 0.0

    def _request(self, url: str, timeout: int) -> requests.Response:
        try:
            resp = requests.get(url, timeout=timeout, headers=self._headers)
        except requests.RequestException as exc:  # pragma: no cover - network dependent
            raise ProviderError(f"SEC request failed: {exc}") from exc
        if resp.status_code == 404:
            raise CompanyNotFound(f"SEC returned 404 for {url}")
        if resp.status_code != 200:
            raise ProviderError(f"SEC returned HTTP {resp.status_code} for {url}")
        return resp

    # --- HTTP helpers ------------------------------------------------------
    def _get_text(self, url: str) -> str:
        """Fetch a filing document. Instances run to several megabytes."""
        return self._request(url, timeout=self._timeout * 4).text

    def _get_text_many(self, urls: dict[str, str | None]) -> dict[str, str | None]:
        """Fetch independent 10-K documents together. SEC's ~10 req/s budget covers this."""
        out: dict[str, str | None] = {key: None for key in urls}
        pending = {key: url for key, url in urls.items() if url}
        if not pending:
            return out
        workers = min(4, len(pending))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {key: pool.submit(self._get_text, url) for key, url in pending.items()}
            for key, fut in futs.items():
                out[key] = fut.result()
        return out

    def _latest_10k(self, ticker: str) -> tuple[str, dict] | None:
        """(CIK, filing row) for the newest 10-K in the submissions feed."""
        cik, _ = self._resolve_cik(ticker)
        recent = self._get_json(f"{self._base_url}/submissions/CIK{cik}.json").get(
            "filings", {}).get("recent", {})
        forms = recent.get("form") or []
        index = next((i for i, form in enumerate(forms) if form == "10-K"), None)
        if index is None:
            return None
        return cik, {key: values[index] for key, values in recent.items()
                     if isinstance(values, list) and len(values) > index}

    def latest_annual_report_id(self, ticker: str) -> str | None:
        found = self._latest_10k(ticker)
        return found[1].get("accessionNumber") if found else None

    def get_annual_report(self, ticker: str) -> AnnualReport | None:
        found = self._latest_10k(ticker)
        if found is None:
            return None
        cik, filing = found
        accession = filing["accessionNumber"]
        folder = f"{self._www_url}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
        items = self._get_json(f"{folder}/index.json").get("directory", {}).get("item", [])
        names = {suffix: next((i["name"] for i in items if i["name"].endswith(suffix)), None)
                 for suffix in ("_htm.xml", "_lab.xml", "_def.xml")}
        if not names["_htm.xml"]:
            return None
        docs = self._get_text_many({
            "instance_xml": f"{folder}/{names['_htm.xml']}",
            "label_xml": f"{folder}/{names['_lab.xml']}" if names["_lab.xml"] else None,
            "definition_xml": f"{folder}/{names['_def.xml']}" if names["_def.xml"] else None,
            "primary_html": (
                f"{folder}/{filing['primaryDocument']}" if filing.get("primaryDocument") else None
            ),
        })
        return AnnualReport(
            accession_number=accession,
            period_end=filing.get("reportDate"),
            instance_xml=docs["instance_xml"] or "",
            label_xml=docs["label_xml"],
            definition_xml=docs["definition_xml"],
            primary_html=docs["primary_html"],
        )

    def _get_json(self, url: str) -> dict:
        resp = self._request(url, timeout=self._timeout)
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
