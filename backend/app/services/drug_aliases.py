"""Generic ↔ brand drug-name aliases.

News refers to drugs by brand name ("Padcev"), while ClinicalTrials.gov uses the
generic / investigational name ("enfortumab vedotin"). This bidirectional map lets
the catalyst→news correlation match either. Curated and clearly finite — unknown
drugs simply get no aliases (no fabrication). Extend as coverage grows.
"""
from __future__ import annotations

import re

# generic (lowercase) -> brand name(s)
_ALIASES: dict[str, list[str]] = {
    # --- Antibody-drug conjugates / oncology (Pfizer / Seagen, others) ---
    "enfortumab vedotin": ["Padcev"],
    "brentuximab vedotin": ["Adcetris"],
    "tucatinib": ["Tukysa"],
    "tisotumab vedotin": ["Tivdak"],
    "talazoparib": ["Talzenna"],
    "enzalutamide": ["Xtandi"],
    "encorafenib": ["Braftovi"],
    "binimetinib": ["Mektovi"],
    "palbociclib": ["Ibrance"],
    "elranatamab": ["Elrexfio"],
    "ritlecitinib": ["Litfulo"],
    "etrasimod": ["Velsipity"],
    "relugolix": ["Orgovyx", "Relumina"],
    "trastuzumab deruxtecan": ["Enhertu"],
    "trastuzumab": ["Herceptin"],
    "pertuzumab": ["Perjeta"],
    "trastuzumab emtansine": ["Kadcyla"],
    "daratumumab": ["Darzalex"],
    "durvalumab": ["Imfinzi"],
    "atezolizumab": ["Tecentriq"],
    "pembrolizumab": ["Keytruda"],
    "nivolumab": ["Opdivo"],
    "olaparib": ["Lynparza"],
    # --- Vertex (cystic fibrosis / pain / gene editing) ---
    "elexacaftor/tezacaftor/ivacaftor": ["Trikafta", "Kaftrio"],
    "ivacaftor": ["Kalydeco"],
    "tezacaftor/ivacaftor": ["Symdeko", "Symkevi"],
    "lumacaftor/ivacaftor": ["Orkambi"],
    "exagamglogene autotemcel": ["Casgevy", "exa-cel", "CTX001"],
    "suzetrigine": ["Journavx", "VX-548"],
    "vanzacaftor/tezacaftor/deutivacaftor": ["Alyftrek"],
    # --- Gilead / Kite ---
    "sacituzumab govitecan": ["Trodelvy"],
    "axicabtagene ciloleucel": ["Yescarta"],
    "brexucabtagene autoleucel": ["Tecartus"],
    "lenacapavir": ["Sunlenca", "Yeztugo"],
    # --- Vaccines / antivirals (Pfizer / Moderna / partners) ---
    "nirmatrelvir/ritonavir": ["Paxlovid"],
    "tozinameran": ["Comirnaty"],
    "elasomeran": ["Spikevax"],
    "somatrogon": ["Ngenla"],
}


def _build_index(mapping: dict[str, list[str]]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for generic, brands in mapping.items():
        names = {generic, *brands}
        for n in names:
            index.setdefault(n.lower(), set()).update(names)
    return index


_INDEX = _build_index(_ALIASES)


# The FDA gives every biologic generic name a meaningless four-letter suffix, so the same
# molecule appears as both "sacituzumab govitecan" and "sacituzumab govitecan-hziy". Exactly
# four letters: "exa-cel" and the like keep their three-letter stems.
_BIOLOGIC_SUFFIX = re.compile(r"-[a-z]{4}$")


def strip_biologic_suffix(term: str) -> str:
    """Drop the FDA's meaningless four-letter suffix: "…govitecan-hziy" -> "…govitecan"."""
    return _BIOLOGIC_SUFFIX.sub("", (term or "").strip())


def expand_aliases(term: str) -> set[str]:
    """Return the full set of known names (generic + brands) for a drug term.

    Empty when the term isn't a known drug — so aliasing never invents a match.
    """
    key = (term or "").strip().lower()
    known = _INDEX.get(key)
    if known is None:
        # Fall back to the unsuffixed form, never the other way round, so an exact match
        # always wins and nothing already working changes.
        known = _INDEX.get(strip_biologic_suffix(key))
    return set(known or set())
