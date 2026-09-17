def test_fetch_requests_independent_endpoints_together():
    from app.providers.fmp_analyst import FmpAnalystProvider

    paths: list[str] = []

    def fake(self, path, params=None):
        paths.append(path)
        if path == "/stable/grades-consensus":
            return {"strongBuy": 1, "buy": 2, "hold": 0, "sell": 0, "strongSell": 0,
                    "consensus": "Buy"}
        if path == "/stable/price-target-consensus":
            return {"targetHigh": 50, "targetLow": 40, "targetConsensus": 45, "targetMedian": 44}
        if path == "/stable/quote":
            return [{"price": 42.0}]
        if path == "/stable/grades":
            return [{"gradingCompany": "Guggenheim", "newGrade": "Buy", "action": "maintain",
                     "date": "2026-08-07"}]
        raise AssertionError(path)

    provider = FmpAnalystProvider(api_key="x")
    provider._try_get = fake.__get__(provider, FmpAnalystProvider)
    data = provider.fetch("PFE")
    assert set(paths) == {
        "/stable/grades-consensus", "/stable/price-target-consensus",
        "/stable/quote", "/stable/grades",
    }
    assert data.consensus.consensus_label == "Buy"
    assert data.consensus.current_price == 42.0
    assert data.consensus.target_consensus == 45
    assert len(data.ratings) == 1
    assert data.warnings == []


def test_fetch_falls_back_to_historical_grades_when_consensus_is_empty():
    from app.providers.fmp_analyst import FmpAnalystProvider

    paths: list[str] = []

    def fake(self, path, params=None):
        paths.append(path)
        if path == "/stable/grades-historical":
            return [{"analystRatingsStrongBuy": 5, "analystRatingsBuy": 3,
                     "analystRatingsHold": 2, "analystRatingsSell": 0,
                     "analystRatingsStrongSell": 0, "date": "2026-01-01"}]
        return None

    provider = FmpAnalystProvider(api_key="x")
    provider._try_get = fake.__get__(provider, FmpAnalystProvider)
    data = provider.fetch("PFE")
    assert "/stable/grades-historical" in paths
    assert data.consensus.analyst_count == 10
    assert data.consensus.consensus_label == "Strong Buy"
