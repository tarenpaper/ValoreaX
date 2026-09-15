"""Per-drug revenue read from a 10-K's XBRL instance (``srt:ProductOrServiceAxis``).

The company-facts API carries no dimensional data, so product-level revenue has to come
from the filing itself: the instance document plus its label and definition linkbases.

Real filings are messy in ways this module handles explicitly:

* Revenue is tagged ``RevenueFromContractWithCustomerExcludingAssessedTax`` by some
  filers and ``Revenues`` by others (Eli Lilly uses the latter for product detail).
* Product facts may be reported worldwide, or only split by geography (US + non-US).
* Therapeutic-area members contain their products — Lilly's Cardiometabolic Health
  includes Mounjaro — so summing every member double counts. The definition linkbase's
  domain-member arcs give the hierarchy, and parents are classified as aggregates.
* Totals, royalty, collaboration, grants and contract manufacturing sit beside drugs.

Everything here is pure: callers pass the document text and get back plain dataclasses.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

# Reused so product revenue and company-level metrics agree on what "annual" means.
from app.services.normalization import _ANNUAL_MAX_DAYS, _ANNUAL_MIN_DAYS

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
DOMAIN_MEMBER = "http://xbrl.org/int/dim/arcrole/domain-member"

PRODUCT_AXIS = "srt:ProductOrServiceAxis"
GEOGRAPHY_AXIS = "srt:StatementGeographicalAxis"
# Axes that label *where* a product's revenue is reported rather than splitting it into
# overlapping pieces. Pfizer reports each product under one business segment and one
# reporting unit (Eliquis: Biopharma → Primary Care). Any other axis is not a clean
# partition and its facts are skipped.
SEGMENT_AXES = frozenset({"us-gaap:StatementBusinessSegmentsAxis", "us-gaap:ReportingUnitAxis"})
# Priority order when a filer reports both tags for the same member and year.
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues")
US_MEMBERS = frozenset({"country:US"})
NON_US_MEMBERS = frozenset({"us-gaap:NonUsMember"})

# Standard taxonomy members that are totals by definition.
TOTAL_MEMBERS = frozenset({
    "us-gaap:ProductMember", "srt:ProductsAndServicesMember", "srt:ProductMember",
})
# Labels that describe a total rather than a drug. Pfizer's "Excluding Comirnaty and
# Paxlovid" deliberately omits two products, so the sum check alone cannot catch it.
_AGGREGATE_PATTERN = re.compile(r"\bexcluding\b|\bexcl\b|\btotal\b", re.I)
_ROYALTY_PATTERN = re.compile(r"royalt|collaborat|licens|alliance|partner|milestone", re.I)
_OTHER_PATTERN = re.compile(r"\bother\b|other(?=[A-Z])|grant|service|manufactur|contract|stand.?ready", re.I)
# A member is treated as a total when it equals the sum of the other products within this
# relative tolerance (filers round to millions).
_SUM_TOLERANCE = 0.005


@dataclass
class ProductYear:
    fiscal_year: int
    value: float              # worldwide revenue, USD
    us_value: float | None
    geography_basis: str      # product_only | us_plus_non_us | regions_unverified | partial
    revenue_tag: str


@dataclass
class ProductLine:
    member: str               # XBRL QName, e.g. "lly:MounjaroMember"
    label: str
    classification: str       # product | royalty_collaboration | aggregate | other
    reason: str
    years: dict[int, ProductYear] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    def latest(self) -> ProductYear | None:
        return self.years[max(self.years)] if self.years else None


def _fragment_to_qname(href: str) -> str | None:
    """`lly-20251231.xsd#lly_MounjaroMember` → `lly:MounjaroMember`.

    SEC filer rules make a schema element id `{prefix}_{localName}`, and prefixes never
    contain underscores, so the first underscore separates them.
    """
    fragment = href.rsplit("#", 1)[-1]
    prefix, _, local = fragment.partition("_")
    return f"{prefix}:{local}" if local else None


def _humanize(member: str) -> str:
    """Readable fallback when a member has no label: `CardiometabolicHealthMember` → `Cardiometabolic Health`."""
    local = member.split(":", 1)[-1].removesuffix("Member")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local).strip() or member


def _annual_product_contexts(root: ET.Element) -> dict[str, tuple[dict[str, str], int]]:
    """Context id → (dimension → member, fiscal year) for annual product-axis contexts."""
    contexts: dict[str, tuple[dict[str, str], int]] = {}
    for context in root.iter(f"{{{XBRLI}}}context"):
        dims = {m.get("dimension"): (m.text or "").strip()
                for m in context.iter(f"{{{XBRLDI}}}explicitMember")}
        if PRODUCT_AXIS not in dims:
            continue
        start = context.find(f".//{{{XBRLI}}}startDate")
        end = context.find(f".//{{{XBRLI}}}endDate")
        if start is None or end is None or not start.text or not end.text:
            continue
        try:
            first, last = date.fromisoformat(start.text.strip()), date.fromisoformat(end.text.strip())
        except ValueError:
            continue
        if _ANNUAL_MIN_DAYS <= (last - first).days <= _ANNUAL_MAX_DAYS:
            contexts[context.get("id")] = (dims, last.year)
    return contexts


Facts = dict[tuple[str, int], dict[str, dict[tuple, dict[str | None, float]]]]


def _revenue_facts(root: ET.Element, contexts: dict) -> Facts:
    """(member, year) → revenue tag → segment key → geography member (None = all) → value.

    The segment key is the sorted (axis, member) pairs from SEGMENT_AXES; () means the
    fact is not placed in any segment.
    """
    facts: Facts = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for element in root:
        if not element.tag.startswith("{"):
            continue
        uri, local = element.tag[1:].split("}", 1)
        if local not in REVENUE_TAGS or "fasb.org/us-gaap" not in uri:
            continue
        context = contexts.get(element.get("contextRef"))
        if context is None or not (element.text or "").strip():
            continue
        dims, year = context
        others = {axis: member for axis, member in dims.items() if axis != PRODUCT_AXIS}
        # Collaboration, consolidation and similar axes are not a clean partition.
        if set(others) - SEGMENT_AXES - {GEOGRAPHY_AXIS}:
            continue
        try:
            value = float(element.text)
        except ValueError:
            continue
        segment = tuple(sorted((axis, member) for axis, member in others.items() if axis in SEGMENT_AXES))
        facts[(dims[PRODUCT_AXIS], year)][local][segment][others.get(GEOGRAPHY_AXIS)] = value
    return facts


def _resolve(by_segment: dict[tuple, dict[str | None, float]]) -> tuple[float, float | None, str]:
    """(worldwide value, US value, basis) across segment placements for one member-year.

    Prefers a fact not placed in any segment. Otherwise uses the least-specific placement;
    when several distinct placements tie, the product is split across them and they sum.
    """
    if () in by_segment:
        return _worldwide(by_segment[()])
    fewest = min(len(key) for key in by_segment)
    placements = [key for key in by_segment if len(key) == fewest]
    if len(placements) == 1:
        value, us, basis = _worldwide(by_segment[placements[0]])
        return value, us, f"single_segment/{basis}"
    resolved = [_worldwide(by_segment[key]) for key in placements]
    us_values = [us for _, us, _ in resolved if us is not None]
    return (sum(v for v, _, _ in resolved), sum(us_values) if len(us_values) == len(resolved) else None,
            "segments_summed")


def _worldwide(by_geography: dict[str | None, float]) -> tuple[float, float | None, str]:
    """(worldwide value, US value, basis) from one tag's facts for a member-year."""
    us = next((v for k, v in by_geography.items() if k in US_MEMBERS), None)
    if None in by_geography:
        return by_geography[None], us, "product_only"
    non_us = next((v for k, v in by_geography.items() if k in NON_US_MEMBERS), None)
    if us is not None and non_us is not None:
        return us + non_us, us, "us_plus_non_us"
    if len(by_geography) > 1:
        return sum(by_geography.values()), us, "regions_unverified"
    return next(iter(by_geography.values())), us, "partial"


def parse_hierarchy(definition_xml: str | None) -> dict[str, set[str]]:
    """Parent member → child members, from domain-member arcs in the definition linkbase.

    Locator labels are local to each extended link, so arcs resolve within their link.
    """
    parents: dict[str, set[str]] = defaultdict(set)
    if not definition_xml:
        return parents
    for link in ET.fromstring(definition_xml).iter(f"{{{LINK}}}definitionLink"):
        locators = {loc.get(f"{{{XLINK}}}label"): _fragment_to_qname(loc.get(f"{{{XLINK}}}href", ""))
                    for loc in link.iter(f"{{{LINK}}}loc")}
        for arc in link.iter(f"{{{LINK}}}definitionArc"):
            if arc.get(f"{{{XLINK}}}arcrole") != DOMAIN_MEMBER:
                continue
            parent = locators.get(arc.get(f"{{{XLINK}}}from"))
            child = locators.get(arc.get(f"{{{XLINK}}}to"))
            if parent and child:
                parents[parent].add(child)
    return parents


def parse_labels(label_xml: str | None) -> dict[str, dict[str, str]]:
    """Member → {role suffix: text}, e.g. {"terseLabel": "Mounjaro", "label": "Mounjaro [Member]"}."""
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    if not label_xml:
        return labels
    for link in ET.fromstring(label_xml).iter(f"{{{LINK}}}labelLink"):
        locators = {loc.get(f"{{{XLINK}}}label"): _fragment_to_qname(loc.get(f"{{{XLINK}}}href", ""))
                    for loc in link.iter(f"{{{LINK}}}loc")}
        resources: dict[str, dict[str, str]] = defaultdict(dict)
        for label in link.iter(f"{{{LINK}}}label"):
            role = (label.get(f"{{{XLINK}}}role") or "").rsplit("/", 1)[-1]
            if label.text:
                resources[label.get(f"{{{XLINK}}}label")][role] = label.text.strip()
        for arc in link.iter(f"{{{LINK}}}labelArc"):
            member = locators.get(arc.get(f"{{{XLINK}}}from"))
            if member and arc.get(f"{{{XLINK}}}to") in resources:
                labels[member].update(resources[arc.get(f"{{{XLINK}}}to")])
    return labels


def _display_label(member: str, roles: dict[str, str]) -> str:
    text = roles.get("terseLabel") or roles.get("label") or ""
    text = re.sub(r"\s*\[Member\]\s*$", "", text).strip()
    return text or _humanize(member)


_GENERIC_NAME_WORDS = frozenset({
    "inc", "corp", "corporation", "company", "holdings", "group", "limited", "plc", "llc",
    "pharmaceuticals", "pharmaceutical", "therapeutics", "biosciences", "biotherapeutics",
    "sciences", "the", "and", "international",
})


def company_name_tokens(registrant_name: str | None) -> set[str]:
    """Distinctive words of a registrant name: "Pfizer Inc." → {"pfizer"}."""
    words = re.findall(r"[A-Za-z]{4,}", registrant_name or "")
    return {w.lower() for w in words} - _GENERIC_NAME_WORDS


def _registrant_name(root: ET.Element) -> str | None:
    for element in root.iter():
        if element.tag.endswith("}EntityRegistrantName") and element.text:
            return element.text.strip()
    return None


def _classify(member: str, label: str, roles: dict[str, str], parent_of: list[str],
              sum_match: list[str] | None, company_tokens: set[str]) -> tuple[str, str]:
    if member in TOTAL_MEMBERS:
        return "aggregate", "A standard taxonomy total, not a single drug."
    if parent_of:
        names = ", ".join(parent_of[:3]) + (" and others" if len(parent_of) > 3 else "")
        return "aggregate", f"Contains {names} in the filing's own hierarchy."
    if sum_match:
        return "aggregate", f"Equals the sum of {', '.join(sum_match[:3])}; treated as a total."
    if _AGGREGATE_PATTERN.search(label):
        return "aggregate", "Labelled as a total or an exclusion subtotal, not a single drug."
    haystack = " ".join([member, label, roles.get("documentation", "")])
    if _ROYALTY_PATTERN.search(haystack):
        return "royalty_collaboration", "Described as royalty, licence or collaboration revenue."
    if _OTHER_PATTERN.search(member.split(":", 1)[-1]) or _OTHER_PATTERN.search(label):
        return "other", "Described as grants, services, manufacturing or an 'other' bucket, not a single drug."
    # Lines named after the company are business units (Pfizer CentreOne, Pfizer Ignite).
    if company_tokens & {w.lower() for w in re.findall(r"[A-Za-z]{4,}", label)}:
        return "other", "Named after the company, which marks a business unit rather than a drug."
    return "product", "Reported as its own product revenue line."


def parse_product_revenue(instance_xml: str, label_xml: str | None = None,
                          definition_xml: str | None = None) -> list[ProductLine]:
    """Product revenue lines from one 10-K, classified, with per-year worldwide values."""
    root = ET.fromstring(instance_xml)
    contexts = _annual_product_contexts(root)
    facts = _revenue_facts(root, contexts)
    hierarchy = parse_hierarchy(definition_xml)
    labels = parse_labels(label_xml)
    company_tokens = company_name_tokens(_registrant_name(root))

    lines: dict[str, ProductLine] = {}
    for (member, year), by_tag in facts.items():
        tag = next((t for t in REVENUE_TAGS if by_tag.get(t)), None)
        if tag is None:
            continue
        value, us_value, basis = _resolve(by_tag[tag])
        line = lines.get(member)
        if line is None:
            line = lines[member] = ProductLine(member=member, label=_display_label(member, labels.get(member, {})),
                                               classification="product", reason="")
        line.years[year] = ProductYear(year, value, us_value, basis, tag)

    reported = set(lines)
    latest_year = max((y for line in lines.values() for y in line.years), default=None)
    for member, line in lines.items():
        # Only children that also report revenue make a member a parent in practice.
        children = sorted(hierarchy.get(member, set()) & reported)
        line.children = children
        child_labels = [lines[c].label for c in children]
        line.classification, line.reason = _classify(
            member, line.label, labels.get(member, {}), child_labels, None, company_tokens)

    # Fallback when a filing has no usable hierarchy: a member equal to the sum of the
    # remaining products is a total (e.g. a "Product sales" line above its franchises).
    if latest_year is not None:
        products = {member: line for member, line in lines.items()
                    if line.classification == "product" and latest_year in line.years}
        for member, line in products.items():
            others = [o for o in products if o != member]
            if len(others) < 2:
                continue
            total = sum(products[o].years[latest_year].value for o in others)
            mine = line.years[latest_year].value
            if total and abs(mine - total) <= _SUM_TOLERANCE * max(abs(mine), abs(total)):
                line.classification, line.reason = _classify(
                    member, line.label, labels.get(member, {}), [],
                    [products[o].label for o in others], company_tokens)

    return sorted(lines.values(), key=lambda line: -(line.latest().value if line.latest() else 0))
