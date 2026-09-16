"""Named baskets whose name is an anagram of their members' initials.

FAANG is not an ordered acronym so much as a *set* of initials that happens to spell a
word — Facebook, Amazon, Apple, Netflix, Google can be listed in any order and the name
still holds. So validation is a perfect matching between the letters of the name and the
companies, not a positional check.

Each company offers two initials: the first letter of its name and the first letter of its
ticker. Alphabet trading as GOOGL can therefore stand for an A or a G, and Eli Lilly (LLY)
for an E or an L. That is the difference between a rule people can actually satisfy and
one that rejects the obvious basket.

Pure functions over plain dicts — no I/O, no ORM.
"""
from __future__ import annotations

MAX_MEMBERS = 7


def initials_for(company_name: str | None, ticker: str | None) -> set[str]:
    """The letters this company may stand for: its name's initial and its ticker's."""
    letters = set()
    for value in (company_name, ticker):
        for char in value or "":
            if char.isalpha():
                letters.add(char.upper())
                break
    return letters


def name_letters(name: str) -> list[str]:
    """The name reduced to its letters, so 'S&P 500' and spacing do not matter."""
    return [char.upper() for char in name or "" if char.isalpha()]


def _assign(letters: list[str], candidates: list[set[str]], used: list[bool]) -> bool:
    """Can every letter be served by a distinct company? Backtracking, ≤7 members."""
    if not letters:
        return True
    letter, rest = letters[0], letters[1:]
    for index, choices in enumerate(candidates):
        if not used[index] and letter in choices:
            used[index] = True
            if _assign(rest, candidates, used):
                return True
            used[index] = False
    return False


def validate_basket_name(name: str, members: list[dict]) -> str | None:
    """Return None when the name works, otherwise a reason the user can act on.

    `members` are dicts with `ticker` and `name`.
    """
    letters = name_letters(name)
    if not letters:
        return "Give the basket a name made of letters, like MANGO."
    if len(members) > MAX_MEMBERS:
        return f"A basket holds at most {MAX_MEMBERS} companies."
    if len(letters) != len(members):
        return (f"{name.upper()} has {len(letters)} letters but the basket has "
                f"{len(members)} compan{'y' if len(members) == 1 else 'ies'} — "
                f"they have to match one to one.")

    candidates = [initials_for(m.get("name"), m.get("ticker")) for m in members]

    # A letter nothing can serve is the clearest failure, so report it first.
    for letter in letters:
        if not any(letter in choices for choices in candidates):
            return f"No company in this basket starts with {letter}."

    if not _assign(letters, candidates, [False] * len(candidates)):
        # Every letter has *some* candidate, so the problem is counting: one company is
        # being asked to cover two letters at once.
        return (f"{name.upper()} needs more companies for some of its letters — "
                f"each company can only supply one.")
    return None


def basket_to_dict(basket, companies_by_ticker: dict) -> dict:
    """Serialize a basket, resolving members to the companies the account holds."""
    members = []
    for ticker in basket.member_tickers():
        company = companies_by_ticker.get(ticker)
        members.append({
            "ticker": ticker,
            "name": company.name if company else None,
            "company_id": company.id if company else None,
            "watched": bool(company.watched) if company else False,
            # A basket can outlive the company row it named, so say so rather than
            # silently dropping the member.
            "available": company is not None,
        })
    return {
        "id": basket.id,
        "name": basket.name,
        "members": members,
        "size": len(members),
        "active": bool(members) and all(m["watched"] for m in members),
    }
