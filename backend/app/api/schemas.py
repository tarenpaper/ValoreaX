"""Marshmallow request schemas (input validation).

Output serialization lives in serializers.py; these schemas only validate and
coerce inbound JSON, raising ValidationError (→ HTTP 422) on bad input.
"""
from __future__ import annotations

from marshmallow import EXCLUDE, Schema, fields, validate

from app.models.common import CatalystOutcome

_OUTCOMES = [o.value for o in CatalystOutcome]


class _Base(Schema):
    class Meta:
        unknown = EXCLUDE  # ignore unexpected keys rather than 500


class IngestRequestSchema(_Base):
    ticker = fields.String(required=True, validate=validate.Length(min=1, max=16))


class CatalystCreateSchema(_Base):
    drug_program = fields.String(required=True, validate=validate.Length(min=1, max=256))
    event_type = fields.String(required=True, validate=validate.Length(min=1, max=32))
    indication = fields.String(load_default=None, validate=validate.Length(max=256), allow_none=True)
    trial_phase = fields.String(load_default=None, validate=validate.Length(max=32), allow_none=True)
    expected_date = fields.Date(load_default=None, allow_none=True)
    actual_date = fields.Date(load_default=None, allow_none=True)
    outcome = fields.String(load_default="pending", validate=validate.OneOf(_OUTCOMES))
    source_url = fields.Url(load_default=None, allow_none=True, require_tld=False)
    notes = fields.String(load_default=None, allow_none=True)


class CatalystUpdateSchema(_Base):
    """All fields optional for PATCH-style updates."""

    drug_program = fields.String(validate=validate.Length(min=1, max=256))
    event_type = fields.String(validate=validate.Length(min=1, max=32))
    indication = fields.String(allow_none=True)
    trial_phase = fields.String(allow_none=True)
    expected_date = fields.Date(allow_none=True)
    actual_date = fields.Date(allow_none=True)
    outcome = fields.String(validate=validate.OneOf(_OUTCOMES))
    source_url = fields.Url(allow_none=True, require_tld=False)
    notes = fields.String(allow_none=True)


class DcfAssumptionsSchema(_Base):
    revenue_growth = fields.Float(required=True, validate=validate.Range(min=-0.99, max=5.0))
    operating_margin = fields.Float(required=True, validate=validate.Range(min=-1.0, max=1.0))
    tax_rate = fields.Float(load_default=0.21, validate=validate.Range(min=0.0, max=0.6))
    capex_pct_revenue = fields.Float(load_default=0.05, validate=validate.Range(min=0.0, max=1.0))
    nwc_pct_revenue = fields.Float(load_default=0.05, validate=validate.Range(min=-1.0, max=1.0))
    wacc = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))
    terminal_growth = fields.Float(load_default=0.025, validate=validate.Range(min=-0.05, max=0.1))
    projection_years = fields.Integer(load_default=5, validate=validate.Range(min=1, max=15))


class DcfInputsSchema(_Base):
    """Optional overrides; when omitted, values are derived from stored SEC metrics."""

    base_revenue = fields.Float(validate=validate.Range(min=0))
    net_debt = fields.Float()
    shares_outstanding = fields.Float(validate=validate.Range(min=0))


class ValuationRequestSchema(_Base):
    assumptions = fields.Nested(DcfAssumptionsSchema, required=True)
    inputs = fields.Nested(DcfInputsSchema, load_default=dict)
    include_sensitivity = fields.Boolean(load_default=True)


class SignalRequestSchema(_Base):
    # Any subset may be supplied; missing inputs simply lower confidence.
    valuation_upside = fields.Float(load_default=None, allow_none=True)
    catalyst_outcome = fields.String(load_default=None, allow_none=True,
                                     validate=validate.OneOf(_OUTCOMES))
    event_type = fields.String(load_default=None, allow_none=True)
    days_to_next_catalyst = fields.Integer(load_default=None, allow_none=True)
    abnormal_return = fields.Float(load_default=None, allow_none=True)
    cash_runway_quarters = fields.Float(load_default=None, allow_none=True)
    analyst_consensus = fields.Float(load_default=None, allow_none=True,
                                     validate=validate.Range(min=-1.0, max=1.0))
    manual_confidence = fields.Float(load_default=None, allow_none=True,
                                     validate=validate.Range(min=0.0, max=1.0))
    as_of_date = fields.Date(load_default=None, allow_none=True)
    auto_derive = fields.Boolean(load_default=True)  # fill gaps from stored data
    persist = fields.Boolean(load_default=True)
