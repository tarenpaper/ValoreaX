"""Unit tests for the live SEC adapter's 10-K document fetch (no network)."""
from __future__ import annotations

from app.providers.sec_edgar import SecEdgarProvider


def _provider():
    return SecEdgarProvider(user_agent="ValoreaX tests@valoreax.dev")


def test_annual_report_fetches_the_four_documents(monkeypatch):
    provider = _provider()
    texts = []

    def fake_json(url):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "PFE", "cik_str": 78003, "title": "PFIZER INC"}}
        if "submissions" in url:
            return {"filings": {"recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000078003-25-000001"],
                "reportDate": ["2024-12-31"],
                "primaryDocument": ["pfe-20241231.htm"],
            }}}
        if url.endswith("index.json"):
            return {"directory": {"item": [
                {"name": "pfe-20241231_htm.xml"},
                {"name": "pfe-20241231_lab.xml"},
                {"name": "pfe-20241231_def.xml"},
            ]}}
        raise AssertionError(url)

    def fake_text(url):
        texts.append(url.split("/")[-1])
        return f"<{url.split('/')[-1]}/>"

    monkeypatch.setattr(provider, "_get_json", fake_json)
    monkeypatch.setattr(provider, "_get_text", fake_text)
    report = provider.get_annual_report("PFE")
    assert report is not None
    assert report.accession_number == "0000078003-25-000001"
    assert set(texts) == {
        "pfe-20241231_htm.xml", "pfe-20241231_lab.xml",
        "pfe-20241231_def.xml", "pfe-20241231.htm",
    }
    assert report.instance_xml == "<pfe-20241231_htm.xml/>"
    assert report.primary_html == "<pfe-20241231.htm/>"


def test_annual_report_skips_missing_optional_linkbases(monkeypatch):
    provider = _provider()
    texts = []

    def fake_json(url):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "PFE", "cik_str": 78003, "title": "PFIZER INC"}}
        if "submissions" in url:
            return {"filings": {"recent": {
                "form": ["10-K"],
                "accessionNumber": ["0000078003-25-000001"],
                "reportDate": ["2024-12-31"],
                "primaryDocument": ["pfe-20241231.htm"],
            }}}
        if url.endswith("index.json"):
            return {"directory": {"item": [{"name": "pfe-20241231_htm.xml"}]}}
        raise AssertionError(url)

    def fake_text(url):
        texts.append(url.split("/")[-1])
        return "<doc/>"

    monkeypatch.setattr(provider, "_get_json", fake_json)
    monkeypatch.setattr(provider, "_get_text", fake_text)
    report = provider.get_annual_report("PFE")
    assert report is not None
    assert set(texts) == {"pfe-20241231_htm.xml", "pfe-20241231.htm"}
    assert report.label_xml is None and report.definition_xml is None
