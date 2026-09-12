"""Configuration readiness; not a claim of successful or fresh retrieval."""
def provider_status(config):
    sources = {
        "SEC": ("SEC_PROVIDER", "sec_edgar", "SEC_USER_AGENT"),
        "Prices": ("MARKET_DATA_PROVIDER", "twelve_data", "TWELVE_DATA_API_KEY"),
        "Trials": ("CATALYST_PROVIDER", "clinicaltrials", None),
        "Analysts": ("ANALYST_PROVIDER", "fmp", "FMP_API_KEY"),
        "News": ("NEWS_PROVIDER", "finnhub", "FINNHUB_API_KEY"),
    }
    result = {}
    for label, (setting, live_provider, credential) in sources.items():
        provider = config.get(setting)
        value = str(config.get(credential, "") or "").strip() if credential else "ready"
        missing = not value or any(part in value.lower() for part in ["example.com", "example@", "your-email", "your_api_key", "change_me"]) or value.lower() == "demo"
        state = "sample" if provider == "mock" else "manual" if provider == "manual" else "unknown"
        if provider == live_provider:
            state = "needs_setup" if missing else "configured"
        result[label] = {"provider": provider, "state": state,
                         "missing_setting": credential if state == "needs_setup" else None}
    return result
