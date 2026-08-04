"""Shared column mixins and controlled vocabularies for the ORM layer."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now (avoids the deprecated naive utcnow())."""
    return datetime.now(UTC)


class TimestampMixin:
    """Adds created_at / updated_at bookkeeping columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class MetricStatus(str, Enum):
    """Extraction confidence/status for a normalized financial value."""

    REPORTED = "reported"        # taken directly from a filed XBRL fact
    DERIVED = "derived"          # computed from other reported facts (e.g. EBITDA)
    ESTIMATED = "estimated"      # heuristic fallback (flagged, lower confidence)
    MISSING = "missing"          # concept not found in the source
    INCONSISTENT = "inconsistent"  # found but failed a sanity/consistency check


class CatalystOutcome(str, Enum):
    PENDING = "pending"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    WITHDRAWN = "withdrawn"


class CatalystEventType(str, Enum):
    """Common clinical / regulatory catalyst types (extensible)."""

    PDUFA = "pdufa"                 # FDA decision date
    ADCOMM = "adcomm"              # advisory committee meeting
    PHASE_READOUT = "phase_readout"  # topline trial data
    TRIAL_START = "trial_start"
    TRIAL_COMPLETION = "trial_completion"
    APPROVAL = "approval"
    CRL = "crl"                    # complete response letter (rejection)
    LABEL_EXPANSION = "label_expansion"
    OTHER = "other"


class SignalType(str, Enum):
    LONG = "long"
    SHORT = "short"
    WATCHLIST = "watchlist"
