"""Workflow guards that enforce broker-specific gates.

A guard inspects a ``Deal`` and its broker's SOP to decide whether the
deal may advance to the next stage.  If the gate is not cleared, the
guard returns a ``GateResult`` describing which documents are still
missing and what actions must be taken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from miles.config.brokers import BrokerSOP, GateRequirement, get_broker_sop
from miles.deals.models import Deal, DealStage, DocumentType


@dataclass
class PendingAction:
    """An action that must be completed before the gate opens."""

    document_type: DocumentType
    urgent: bool
    request_message: str


@dataclass
class GateResult:
    """Outcome of evaluating a deal against its broker's gate rules.

    Attributes
    ----------
    cleared:
        ``True`` when all gate requirements have been satisfied.
    pending_actions:
        Documents still needed (empty when ``cleared`` is ``True``).
    broker_sop:
        The SOP that was evaluated, or ``None`` for default-pipeline deals.
    playbook_slug:
        Supabase ``process_playbooks`` slug governing this gate, if any.
    """

    cleared: bool
    pending_actions: list[PendingAction] = field(default_factory=list)
    broker_sop: Optional[BrokerSOP] = None
    playbook_slug: Optional[str] = None


def evaluate_gate(deal: Deal) -> GateResult:
    """Check whether *deal* satisfies its broker's document gate.

    If the broker has no SOP the gate is considered cleared and the deal
    may proceed normally through the default pipeline.
    """
    if deal.broker is None:
        return GateResult(cleared=True)

    sop = get_broker_sop(deal.broker.name)
    if sop is None:
        return GateResult(cleared=True)

    pending: list[PendingAction] = []
    for req in sop.gate_documents:
        if not deal.has_document(req.document_type):
            pending.append(
                PendingAction(
                    document_type=req.document_type,
                    urgent=req.urgent,
                    request_message=req.request_message or (
                        f"Please provide {req.document_type.value}."
                    ),
                )
            )

    playbook_slug = _resolve_playbook_slug(sop)

    return GateResult(
        cleared=len(pending) == 0,
        pending_actions=pending,
        broker_sop=sop,
        playbook_slug=playbook_slug,
    )


def may_send_full_details(deal: Deal) -> bool:
    """Return ``True`` only if the deal is allowed to receive full
    details, packages, or expanded materials.

    For deals governed by a broker SOP with
    ``block_full_details_until_gate_cleared=True``, this returns ``False``
    until every gate document has been received.
    """
    result = evaluate_gate(deal)
    if result.broker_sop is None:
        return True
    if not result.broker_sop.block_full_details_until_gate_cleared:
        return True
    return result.cleared


# ---------------------------------------------------------------------------
# Playbook slug mapping
# ---------------------------------------------------------------------------

_PLAYBOOK_SLUGS: dict[str, str] = {
    "martin winter": "martin-winter-pof-loi-gate",
}


def _resolve_playbook_slug(sop: BrokerSOP) -> Optional[str]:
    return _PLAYBOOK_SLUGS.get(sop.broker_name.lower())
