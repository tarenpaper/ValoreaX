"""A fictional 10-K for the sample company, so drug modelling runs offline.

The XBRL here mirrors the structures verified in real FY2025 filings — unprefixed
``<context>`` elements, ``xbrldi:explicitMember`` dimensions on
``srt:ProductOrServiceAxis``, and a label linkbase carrying the human-readable product
names — so the same parser handles mock and live filings identically.

Everything is **fictional sample data**. The drug names, patient counts and patent years
do not describe any real product.
"""
from __future__ import annotations

from .base import AnnualReport

PERIOD_END = "2025-12-31"
ACCESSION = "0009000001-26-000001"

# member -> (label, {fiscal year: worldwide revenue}). Each year sums to that year's
# total revenue in `mock_provider`, the way a real filing's product table does.
_PRODUCTS: dict[str, tuple[str, dict[int, float]]] = {
    "valx:TrevaronMember": ("Trevaron", {2023: 470e6, 2024: 620e6, 2025: 800e6}),
    "valx:KelvidoMember": ("Kelvido", {2023: 210e6, 2024: 260e6, 2025: 330e6}),
    "valx:CollaborationAndRoyaltyMember": ("Collaboration and royalty revenue",
                                           {2023: 140e6, 2024: 140e6, 2025: 160e6}),
}

_NS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:srt="http://fasb.org/srt/2025" '
    'xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:valx="http://www.example.com/valx/20251231">'
)
_LINKBASE = ('<?xml version="1.0" encoding="utf-8"?><link:linkbase '
             'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">')


def instance_xml(registrant: str) -> str:
    parts = [_NS,
             '<context id="dei"><entity><identifier scheme="http://www.sec.gov/CIK">9000001</identifier>'
             f'</entity><period><instant>{PERIOD_END}</instant></period></context>',
             f'<dei:EntityRegistrantName contextRef="dei">{registrant}</dei:EntityRegistrantName>']
    for index, (member, (_, years)) in enumerate(_PRODUCTS.items()):
        for year, value in sorted(years.items()):
            ctx = f"c-{index}-{year}"
            parts.append(
                f'<context id="{ctx}"><entity>'
                '<identifier scheme="http://www.sec.gov/CIK">9000001</identifier>'
                '<segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">'
                f'{member}</xbrldi:explicitMember></segment></entity>'
                f'<period><startDate>{year}-01-01</startDate><endDate>{year}-12-31</endDate></period>'
                '</context>'
                '<us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax '
                f'contextRef="{ctx}" decimals="-6" unitRef="usd">{value:.0f}'
                '</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>')
    parts.append("</xbrl>")
    return "".join(parts)


def label_xml() -> str:
    body = []
    for member, (label, _) in _PRODUCTS.items():
        tag = member.replace(":", "_")
        body += [f'<link:loc xlink:type="locator" xlink:label="loc_{tag}" xlink:href="valx.xsd#{tag}"/>',
                 f'<link:label xlink:label="lab_{tag}" xlink:type="resource" '
                 f'xlink:role="http://www.xbrl.org/2003/role/terseLabel">{label}</link:label>',
                 '<link:labelArc xlink:type="arc" '
                 'xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" '
                 f'xlink:from="loc_{tag}" xlink:to="lab_{tag}"/>']
    return f'{_LINKBASE}<link:labelLink xlink:type="extended">{"".join(body)}</link:labelLink></link:linkbase>'


PRIMARY_HTML = """<html><body>
<p><b>SAMPLE FILING — FICTIONAL DATA.</b> Valorea Therapeutics, Inc. is a sample company.
No product, patient population or patent described below is real.</p>

<h2>Item 1. Business</h2>
<p>We market two approved medicines. TREVARON (trevaronib) is approved for the treatment of
metabolic hepatic fibrosis, a disease that affects approximately 90,000 people in our target
markets. KELVIDO (kelvidostat) is approved for refractory hypercalciuria, which affects
approximately 40,000 people in the United States.</p>

<p>We are advancing three pipeline programs. VLX-410 is in Phase 3 development for autoimmune
kidney disease, which affects approximately 100,000 people in the United States. VLX-228 is in
Phase 2 development for hereditary anemia. VLX-905 is in Phase 1 development for solid tumors.</p>

<h2>Intellectual Property</h2>
<p>Our composition of matter patent covering TREVARON expires in 2036 in the United States and
in 2037 in the European Union. Data exclusivity for TREVARON in the United States expires in
2029. The composition of matter patent covering KELVIDO expires in 2033 in the United States.</p>
<p>These expiration dates do not reflect potential patent term extensions or pediatric
exclusivity.</p>
</body></html>"""


def annual_report(registrant: str) -> AnnualReport:
    return AnnualReport(accession_number=ACCESSION, period_end=PERIOD_END,
                        instance_xml=instance_xml(registrant), label_xml=label_xml(),
                        definition_xml=None, primary_html=PRIMARY_HTML)
