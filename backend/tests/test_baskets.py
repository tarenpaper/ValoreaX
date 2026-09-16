"""The acronym rule, and the capped watchlist it populates."""
from __future__ import annotations

from app.services.baskets import initials_for, validate_basket_name

V1 = "/api/v1"

MANGO = [
    {"ticker": "MRNA", "name": "Moderna, Inc."},
    {"ticker": "AMGN", "name": "Amgen Inc."},
    {"ticker": "NVAX", "name": "Novavax, Inc."},
    {"ticker": "GILD", "name": "Gilead Sciences, Inc."},
    {"ticker": "OGN", "name": "Organon & Co."},
]


# --- The rule ----------------------------------------------------------------------
def test_a_word_spelled_by_the_members_initials_is_accepted():
    assert validate_basket_name("MANGO", MANGO) is None
    # It is an anagram, not an ordering: the same companies in any order still spell it.
    assert validate_basket_name("MANGO", list(reversed(MANGO))) is None


def test_the_order_of_the_letters_does_not_have_to_match_the_members():
    assert validate_basket_name("GONMA", MANGO) is None


def test_a_letter_no_company_supplies_is_named_in_the_reason():
    reason = validate_basket_name("MANGZ", MANGO)
    assert reason and "starts with Z" in reason


def test_one_company_cannot_cover_two_of_the_same_letter():
    """AAAAA has five A's but only Amgen can supply one."""
    reason = validate_basket_name("AAAAA", MANGO)
    assert reason and "each company can only supply one" in reason


def test_duplicate_initials_are_matched_one_for_one():
    """Both start with A, so a name needs two A's — one company cannot cover both."""
    pair = [{"ticker": "AMGN", "name": "Amgen"}, {"ticker": "ABBV", "name": "AbbVie"}]
    assert validate_basket_name("AA", pair) is None
    assert validate_basket_name("AB", pair) is not None    # nothing here supplies a B
    # Only the *first* letter counts, so ABBV never stands for its second B.
    assert initials_for("AbbVie", "ABBV") == {"A"}

    mixed = [{"ticker": "AMGN", "name": "Amgen"}, {"ticker": "BIIB", "name": "Biogen"}]
    assert validate_basket_name("AB", mixed) is None
    assert validate_basket_name("BB", mixed) is not None   # only one company offers a B


def test_a_ticker_initial_counts_as_well_as_the_company_name():
    """Alphabet trades as GOOGL, so it can stand for either letter."""
    assert initials_for("Alphabet", "GOOGL") == {"A", "G"}
    assert initials_for("Eli Lilly and Company", "LLY") == {"E", "L"}
    maang = [
        {"ticker": "META", "name": "Meta Platforms"}, {"ticker": "AMZN", "name": "Amazon"},
        {"ticker": "AAPL", "name": "Apple"}, {"ticker": "NFLX", "name": "Netflix"},
        {"ticker": "GOOGL", "name": "Alphabet"},
    ]
    assert validate_basket_name("MAANG", maang) is None


def test_the_name_must_have_one_letter_per_company():
    reason = validate_basket_name("MANGOS", MANGO)
    assert reason and "6 letters" in reason and "5 companies" in reason


def test_punctuation_and_spacing_in_the_name_are_ignored():
    assert validate_basket_name("m-a-n-g-o", MANGO) is None


# --- The capped list ---------------------------------------------------------------
def _watch(client, ticker):
    return client.post(f"{V1}/watchlist", json={"ticker": ticker})


def test_the_watchlist_is_capped_and_says_what_is_in_the_way(app, client):
    app.config["WATCHLIST_LIMIT"] = 2
    assert _watch(client, "VALX").status_code == 201
    assert _watch(client, "HELX").status_code == 201

    full = _watch(client, "CARO")
    assert full.status_code == 409
    error = full.get_json()["error"]
    assert error["code"] == "watchlist_full"
    assert set(error["details"]["watching"]) == {"VALX", "HELX"}
    assert "Remove one" in error["message"]
    assert client.get(f"{V1}/watchlist").get_json()["remaining"] == 0


def test_removing_a_company_frees_a_slot_and_keeps_its_data(app, client):
    app.config["WATCHLIST_LIMIT"] = 1
    _watch(client, "VALX")
    metrics_before = client.get(f"{V1}/companies/VALX/metrics").get_json()["count"]

    removed = client.delete(f"{V1}/watchlist/VALX")
    assert removed.status_code == 200 and removed.get_json()["watched"] is False
    assert "kept" in removed.get_json()["note"]

    body = client.get(f"{V1}/watchlist").get_json()
    assert body["count"] == 0 and body["remaining"] == 1
    # Unwatched, not deleted: the company and everything downloaded for it survive.
    assert client.get(f"{V1}/companies/VALX/metrics").get_json()["count"] == metrics_before
    assert "VALX" in {c["ticker"] for c in client.get(f"{V1}/companies").get_json()["companies"]}


def test_re_adding_a_stored_company_costs_no_provider_call(app, client, monkeypatch):
    app.config["WATCHLIST_LIMIT"] = 2
    _watch(client, "VALX")
    client.delete(f"{V1}/watchlist/VALX")

    def refuse(*args, **kwargs):
        raise AssertionError("re-watching a stored company must not re-ingest it")

    monkeypatch.setattr("app.api.v1.watchlist.ingest_company", refuse)
    again = _watch(client, "VALX")
    assert again.status_code == 201 and again.get_json()["ingested"] is False


def test_an_account_already_over_the_cap_is_never_truncated(app, client):
    for ticker in ("VALX", "HELX", "CARO"):
        _watch(client, ticker)
    app.config["WATCHLIST_LIMIT"] = 2          # the cap tightens under them

    body = client.get(f"{V1}/watchlist").get_json()
    assert body["count"] == 3 and body["remaining"] == 0
    assert _watch(client, "VALX").status_code == 200   # already watched: no-op, not an error


# --- Baskets over HTTP -------------------------------------------------------------
def _stock_workspace(client):
    for ticker in ("VALX", "HELX", "CARO"):
        _watch(client, ticker)


def test_a_basket_is_created_from_stored_companies_and_can_be_activated(app, client):
    _stock_workspace(client)
    names = {c["ticker"]: c["name"] for c in client.get(f"{V1}/companies").get_json()["companies"]}
    assert names["VALX"].startswith("Valorea") and names["CARO"].startswith("Cardyx")

    created = client.post(f"{V1}/baskets", json={"name": "CV", "tickers": ["CARO", "VALX"]})
    assert created.status_code == 201, created.get_json()
    basket = created.get_json()
    assert basket["name"] == "CV" and basket["size"] == 2
    assert [m["ticker"] for m in basket["members"]] == ["CARO", "VALX"]

    activated = client.post(f"{V1}/baskets/{basket['id']}/activate")
    assert activated.status_code == 200
    assert set(activated.get_json()["watching"]) == {"CARO", "VALX"}
    # Activating swaps the list: HELX is dropped, but its data stays.
    watched = {c["ticker"] for c in client.get(f"{V1}/watchlist").get_json()["companies"]}
    assert watched == {"CARO", "VALX"}
    assert client.get(f"{V1}/companies/HELX/metrics").get_json()["count"] > 0


def test_a_name_that_is_not_an_anagram_of_the_initials_is_refused(client):
    _stock_workspace(client)
    bad = client.post(f"{V1}/baskets", json={"name": "ZZ", "tickers": ["CARO", "VALX"]})
    assert bad.status_code == 422
    assert bad.get_json()["error"]["code"] == "basket_name_mismatch"
    assert "starts with Z" in bad.get_json()["error"]["message"]


def test_a_basket_cannot_name_companies_the_account_does_not_hold(client):
    _stock_workspace(client)
    resp = client.post(f"{V1}/baskets", json={"name": "CZ", "tickers": ["CARO", "ZZZZ"]})
    assert resp.status_code == 422 and "ZZZZ" in resp.get_json()["error"]["message"]


def test_deleting_a_basket_leaves_its_companies_alone(client):
    _stock_workspace(client)
    basket = client.post(f"{V1}/baskets", json={"name": "CV", "tickers": ["CARO", "VALX"]}).get_json()
    assert client.delete(f"{V1}/baskets/{basket['id']}").get_json()["deleted"] is True
    assert client.get(f"{V1}/baskets").get_json()["count"] == 0
    assert client.get(f"{V1}/watchlist").get_json()["count"] == 3


def test_another_account_cannot_see_or_touch_these_baskets(app, client, token_for):
    _stock_workspace(client)
    basket = client.post(f"{V1}/baskets", json={"name": "CV", "tickers": ["CARO", "VALX"]}).get_json()

    other = app.test_client()
    other.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token_for('22222222-2222-4222-8222-222222222222')}"
    assert other.get(f"{V1}/baskets").get_json()["count"] == 0
    assert other.post(f"{V1}/baskets/{basket['id']}/activate").status_code == 404
    assert other.delete(f"{V1}/baskets/{basket['id']}").status_code == 404


def test_a_duplicate_basket_name_is_reported_as_a_conflict(client):
    _stock_workspace(client)
    body = {"name": "CV", "tickers": ["CARO", "VALX"]}
    assert client.post(f"{V1}/baskets", json=body).status_code == 201
    clash = client.post(f"{V1}/baskets", json=body)
    assert clash.status_code == 409 and "already have a basket called CV" in clash.get_json()["error"]["message"]
    # The failed insert must not poison the session for the next request.
    assert client.get(f"{V1}/baskets").get_json()["count"] == 1
