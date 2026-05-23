"""Broker-specific operational standards (SOPs).

Each broker can have custom rules that control how deals from that broker
are processed.  Rules are looked up by *broker name* (case-insensitive).
Only brokers with explicit entries here receive special treatment; all
others follow the default pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from miles.deals.models import AnalysisMetric, DocumentType, FrameOfReference


@dataclass(frozen=True)
class GateRequirement:
    """A document that must be collected before advancing past a gate."""

    document_type: DocumentType
    urgent: bool = False
    request_message: Optional[str] = None


@dataclass(frozen=True)
class AnalysisFrameConfig:
    """Secondary analysis requirements for a broker's deals.

    Specifies the frame of reference and the metrics that must be
    evaluated when analyzing deals from this broker.
    """

    frame_of_reference: FrameOfReference
    required_metrics: tuple[AnalysisMetric, ...]
    analysis_priority: str = "standard"
    description: str = ""


@dataclass(frozen=True)
class BrokerSOP:
    """Operational standard for a specific broker.

    Attributes
    ----------
    broker_name:
        Canonical name used for matching (case-insensitive).
    gate_documents:
        Documents that must be received *before* any full deal package,
        expanded materials, or detailed information is shared.
    block_full_details_until_gate_cleared:
        When ``True``, the router will refuse to send full details until
        every document in ``gate_documents`` has been received.
    analysis_frame:
        Secondary analysis frame applied after the document gate clears.
        ``None`` means no special analysis requirements.
    notes:
        Free-form operational notes for team reference.
    """

    broker_name: str
    gate_documents: tuple[GateRequirement, ...] = ()
    block_full_details_until_gate_cleared: bool = True
    analysis_frame: Optional[AnalysisFrameConfig] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BROKER_SOPS: dict[str, BrokerSOP] = {}


def register_broker_sop(sop: BrokerSOP) -> None:
    """Add or replace a broker SOP in the registry."""
    _BROKER_SOPS[sop.broker_name.lower()] = sop


def get_broker_sop(broker_name: str) -> Optional[BrokerSOP]:
    """Look up the SOP for *broker_name* (case-insensitive).

    Returns ``None`` when no special SOP is configured — the deal should
    follow the default pipeline.
    """
    return _BROKER_SOPS.get(broker_name.strip().lower())


def list_broker_sops() -> list[BrokerSOP]:
    """Return all registered broker SOPs."""
    return list(_BROKER_SOPS.values())


# ---------------------------------------------------------------------------
# Martin Winter SOP
# ---------------------------------------------------------------------------

MARTIN_WINTER_ANALYSIS_FRAME = AnalysisFrameConfig(
    frame_of_reference=FrameOfReference.LARGE_MULTIFAMILY_PROFESSIONAL,
    required_metrics=(
        AnalysisMetric.RENT_COMPS,
        AnalysisMetric.OCCUPANCY,
        AnalysisMetric.EXPENSE_RATIOS,
        AnalysisMetric.NOI,
        AnalysisMetric.CAP_RATE,
    ),
    analysis_priority="high",
    description=(
        "Large multifamily professional analysis frame. Evaluate "
        "rent comps, occupancy, expense ratios, NOI, and cap rate "
        "for all Martin Winter deals once the POF/LOI gate clears."
    ),
)

MARTIN_WINTER_SOP = BrokerSOP(
    broker_name="Martin Winter",
    gate_documents=(
        GateRequirement(
            document_type=DocumentType.PROOF_OF_FUNDS,
            urgent=True,
            request_message=(
                "Before we can share full deal details, we need a current "
                "Proof of Funds (POF). Please send at your earliest "
                "convenience so we can move forward quickly."
            ),
        ),
        GateRequirement(
            document_type=DocumentType.LETTER_OF_INTENT,
            urgent=True,
            request_message=(
                "We also require a signed Letter of Intent (LOI) before "
                "releasing the full deal package. Please provide this "
                "alongside the POF."
            ),
        ),
    ),
    block_full_details_until_gate_cleared=True,
    analysis_frame=MARTIN_WINTER_ANALYSIS_FRAME,
    notes=(
        "Standard operating procedure for all Martin Winter deal flow. "
        "Layer 1: Every deal must trigger an urgent request for POF and "
        "LOI first — no full details until both are received. "
        "Layer 2: Once gate clears, apply large multifamily professional "
        "analysis frame (rent comps, occupancy, expense ratios, NOI, "
        "cap rate) before releasing the full package."
    ),
)

register_broker_sop(MARTIN_WINTER_SOP)
