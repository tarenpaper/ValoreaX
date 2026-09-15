"""Product revenue from 10-K XBRL (srt:ProductOrServiceAxis).

Fixtures are generated to mirror structures verified in real FY2025 filings: unprefixed
<context> elements in the xbrli namespace, xbrldi:explicitMember dimensions, us-gaap
facts, and label/definition linkbases whose locator labels carry unique suffixes.
"""
from __future__ import annotations

import uuid

from app.services.product_revenue import company_name_tokens, parse_product_revenue

# --- Fixture builders -----------------------------------------------------------
_INSTANCE_HEAD = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:srt="http://fasb.org/srt/2025" '
    'xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:country="http://xbrl.sec.gov/country/2025" '
    'xmlns:co="http://www.example.com/20251231">'
)


def instance(facts, registrant="Example Therapeutics, Inc."):
    """facts: (tag, value, {axis: member}, year[, days]) tuples."""
    parts = [_INSTANCE_HEAD,
             '<context id="dei"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier></entity>'
             '<period><instant>2025-12-31</instant></period></context>',
             f'<dei:EntityRegistrantName contextRef="dei">{registrant}</dei:EntityRegistrantName>']
    for index, fact in enumerate(facts):
        tag, value, dims, year = fact[:4]
        days = fact[4] if len(fact) > 4 else 364
        start = f"{year}-01-01" if days > 100 else f"{year}-10-01"
        members = "".join(f'<xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>'
                          for axis, member in dims.items())
        parts.append(
            f'<context id="c-{index}"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier>'
            f'<segment>{members}</segment></entity>'
            f'<period><startDate>{start}</startDate><endDate>{year}-12-31</endDate></period></context>'
            f'<us-gaap:{tag} contextRef="c-{index}" decimals="-6" unitRef="usd">{value}</us-gaap:{tag}>')
    parts.append("</xbrl>")
    return "".join(parts)


_LINKBASE_HEAD = ('<?xml version="1.0" encoding="utf-8"?><link:linkbase '
                  'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">')


def _loc(member):
    label = f"loc_{member.replace(':', '_')}_{uuid.uuid4()}"
    href = f"co-20251231.xsd#{member.replace(':', '_')}"
    return label, f'<link:loc xlink:type="locator" xlink:label="{label}" xlink:href="{href}"/>'


def labels(mapping):
    """mapping: member -> terse label (a standard "[Member]" label is also emitted)."""
    body = []
    for member, text in mapping.items():
        loc_label, loc = _loc(member)
        resource = f"lab_{member.replace(':', '_')}"
        body += [loc,
                 f'<link:label xlink:label="{resource}" xlink:role="http://www.xbrl.org/2003/role/terseLabel" '
                 f'xlink:type="resource">{text}</link:label>',
                 f'<link:label xlink:label="{resource}" xlink:role="http://www.xbrl.org/2003/role/label" '
                 f'xlink:type="resource">{text} [Member]</link:label>',
                 f'<link:labelArc xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" '
                 f'xlink:from="{loc_label}" xlink:to="{resource}" xlink:type="arc"/>']
    return f'{_LINKBASE_HEAD}<link:labelLink xlink:type="extended">{"".join(body)}</link:labelLink></link:linkbase>'


def definitions(arcs):
    """arcs: (parent, child) domain-member pairs, all in one extended link."""
    body = []
    for parent, child in arcs:
        parent_label, parent_loc = _loc(parent)
        child_label, child_loc = _loc(child)
        body += [parent_loc, child_loc,
                 f'<link:definitionArc xlink:arcrole="http://xbrl.org/int/dim/arcrole/domain-member" '
                 f'xlink:from="{parent_label}" xlink:to="{child_label}" xlink:type="arc"/>']
    return (f'{_LINKBASE_HEAD}<link:definitionLink xlink:type="extended">{"".join(body)}'
            f'</link:definitionLink></link:linkbase>')


P = "srt:ProductOrServiceAxis"
G = "srt:StatementGeographicalAxis"
RFC = "RevenueFromContractWithCustomerExcludingAssessedTax"


def by_label(lines):
    return {line.label: line for line in lines}


# --- Vertex-style: product-only contexts, standard total, other and royalty ------
def test_product_only_lines_are_classified_and_valued():
    facts = [(RFC, 11_971e6, {P: "us-gaap:ProductMember"}, 2025),
             (RFC, 10_313e6, {P: "co:TrikaftaMember"}, 2025),
             (RFC, 9_800e6, {P: "co:TrikaftaMember"}, 2024),
             (RFC, 838e6, {P: "co:AlyftrekMember"}, 2025),
             (RFC, 820e6, {P: "co:ManufacturedProductOtherMember"}, 2025),
             (RFC, 31e6, {P: "co:CollaborativeandRoyaltyMember"}, 2025)]
    lines = by_label(parse_product_revenue(
        instance(facts),
        labels({"co:TrikaftaMember": "TRIKAFTA/KAFTRIO", "co:AlyftrekMember": "ALYFTREK",
                "co:ManufacturedProductOtherMember": "Other product revenues",
                "co:CollaborativeandRoyaltyMember": "Other revenues"})))

    trikafta = lines["TRIKAFTA/KAFTRIO"]
    assert trikafta.classification == "product"
    assert trikafta.latest().value == 10_313e6
    assert trikafta.latest().geography_basis == "product_only"
    assert sorted(trikafta.years) == [2024, 2025]
    assert lines["Product"].classification == "aggregate"           # label humanized; standard total
    assert lines["Other product revenues"].classification == "other"
    assert lines["Other revenues"].classification == "royalty_collaboration"


# --- Lilly-style: product × geography, parents in the hierarchy, Revenues tag -----
def test_geography_partition_sums_and_parents_do_not_double_count():
    facts = [("Revenues", 13_651e6, {P: "co:MounjaroMember", G: "country:US"}, 2025),
             ("Revenues", 9_315e6, {P: "co:MounjaroMember", G: "us-gaap:NonUsMember"}, 2025),
             ("Revenues", 3_432e6, {P: "co:JardianceMember"}, 2025),
             ("Revenues", 33_864e6, {P: "co:CardiometabolicHealthMember", G: "country:US"}, 2025),
             ("Revenues", 14_357e6, {P: "co:CardiometabolicHealthMember", G: "us-gaap:NonUsMember"}, 2025),
             ("Revenues", 4_006e6, {P: "co:OtherCardiometabolicHealthMember", G: "country:US"}, 2025),
             ("Revenues", 0.0, {P: "co:OtherCardiometabolicHealthMember", G: "us-gaap:NonUsMember"}, 2025)]
    lines = by_label(parse_product_revenue(
        instance(facts),
        labels({"co:MounjaroMember": "Mounjaro", "co:JardianceMember": "Jardiance",
                "co:CardiometabolicHealthMember": "Cardiometabolic Health",
                "co:OtherCardiometabolicHealthMember": "Other cardiometabolic health"}),
        definitions([("co:CardiometabolicHealthMember", "co:MounjaroMember"),
                     ("co:CardiometabolicHealthMember", "co:JardianceMember"),
                     ("co:CardiometabolicHealthMember", "co:OtherCardiometabolicHealthMember")])))

    mounjaro = lines["Mounjaro"].latest()
    assert mounjaro.value == 13_651e6 + 9_315e6
    assert mounjaro.us_value == 13_651e6
    assert mounjaro.geography_basis == "us_plus_non_us"
    assert mounjaro.revenue_tag == "Revenues"

    parent = lines["Cardiometabolic Health"]
    assert parent.classification == "aggregate"
    assert "Mounjaro" in parent.reason
    assert lines["Other cardiometabolic health"].classification == "other"
    # Summing only products never includes the parent that contains them.
    products = [line for line in lines.values() if line.classification == "product"]
    assert {line.label for line in products} == {"Mounjaro", "Jardiance"}


# --- Pfizer-style: product × segment × reporting unit, business units, exclusions --
def test_segment_placement_business_units_and_exclusion_totals():
    segment = {"us-gaap:StatementBusinessSegmentsAxis": "co:BiopharmaSegmentMember",
               "us-gaap:ReportingUnitAxis": "co:PrimaryCareMember"}
    facts = [(RFC, 7_960e6, {P: "co:EliquisMember", **segment}, 2025),
             (RFC, 54_470e6, {P: "co:ExcludingComirnatyAndPaxlovidMember"}, 2025),
             (RFC, 1_338e6, {P: "co:CentreOneMember"}, 2025),
             (RFC, 2_190e6, {P: "co:XtandiMember", **segment}, 2025)]
    lines = by_label(parse_product_revenue(
        instance(facts, registrant="Pfizer Inc."),
        labels({"co:EliquisMember": "Eliquis", "co:CentreOneMember": "Pfizer CentreOne",
                "co:ExcludingComirnatyAndPaxlovidMember": "Excluding Comirnaty and Paxlovid",
                "co:XtandiMember": "Xtandi alliance revenues"})))

    eliquis = lines["Eliquis"]
    assert eliquis.classification == "product"
    assert eliquis.latest().value == 7_960e6
    assert eliquis.latest().geography_basis.startswith("single_segment")
    assert lines["Pfizer CentreOne"].classification == "other"
    assert "business unit" in lines["Pfizer CentreOne"].reason
    assert lines["Excluding Comirnaty and Paxlovid"].classification == "aggregate"
    assert lines["Xtandi alliance revenues"].classification == "royalty_collaboration"


# --- Moderna-style: no hierarchy, a total equal to its franchises ------------------
def test_total_detected_by_sum_when_no_hierarchy_exists():
    facts = [(RFC, 1_818e6, {P: "co:ProductSalesMember"}, 2025),
             (RFC, 1_810e6, {P: "co:COVID19Member"}, 2025),
             (RFC, 8e6, {P: "co:RSVMember"}, 2025)]
    lines = by_label(parse_product_revenue(
        instance(facts), labels({"co:ProductSalesMember": "Net product sales", "co:COVID19Member": "COVID",
                                 "co:RSVMember": "RSV"})))
    assert lines["Net product sales"].classification == "aggregate"
    assert "COVID" in lines["Net product sales"].reason
    assert lines["COVID"].classification == "product"
    assert lines["RSV"].classification == "product"


# --- Hazards ----------------------------------------------------------------------
def test_quarters_unclean_axes_and_partial_geography():
    facts = [(RFC, 500e6, {P: "co:AlphaMember"}, 2025, 91),                              # a quarter
             (RFC, 900e6, {P: "co:AlphaMember", "co:CollaborationAxis": "co:PartnerMember"}, 2025),
             (RFC, 300e6, {P: "co:BetaMember", G: "country:US"}, 2025)]                   # US only
    lines = by_label(parse_product_revenue(instance(facts), labels({"co:BetaMember": "Beta"})))
    assert "Alpha" not in lines               # neither the quarter nor the unclean axis counts
    assert lines["Beta"].latest().geography_basis == "partial"
    assert lines["Beta"].latest().us_value == 300e6


def test_revenue_tag_priority_when_both_are_reported():
    facts = [("Revenues", 1_000e6, {P: "co:GammaMember"}, 2025),
             (RFC, 950e6, {P: "co:GammaMember"}, 2025)]
    gamma = by_label(parse_product_revenue(instance(facts), labels({"co:GammaMember": "Gamma"})))["Gamma"]
    assert gamma.latest().value == 950e6
    assert gamma.latest().revenue_tag == RFC


def test_labels_fall_back_to_humanized_member_names():
    facts = [(RFC, 10e6, {P: "co:NeuroscienceFranchiseMember"}, 2025)]
    lines = by_label(parse_product_revenue(instance(facts)))
    assert "Neuroscience Franchise" in lines


def test_company_name_tokens_ignore_generic_words():
    assert company_name_tokens("Pfizer Inc.") == {"pfizer"}
    assert company_name_tokens("Vertex Pharmaceuticals Incorporated") == {"vertex", "incorporated"}
    assert company_name_tokens(None) == set()
