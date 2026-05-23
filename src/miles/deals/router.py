"""Deal intake router.

Accepts inbound deals, applies broker-specific SOP rules, and determines
the next pipeline action.  The router is the single entry-point for all
new deals — it guarantees that broker gates are enforced before any full
details or packages are released.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from miles.config.brokers import get_broker_sop
from miles.deals.models import BrokerContact, Deal, DealStage
from miles.notifications.templates import (
    render_document_request,
    render_full_package_blocked_notice,
)
from miles.workflows.guards import GateResult, evaluate_gate, may_send_full_details

logger = logging.getLogger(__name__)

# Supabase project reference
SUPABASE_PROJECT_ID = "egpqhzubdeklzstzdmtt"


@dataclass
class RoutingDecision:
    """The result of routing an inbound deal.

    Attributes
    ----------
    deal:
        The deal after any stage transitions.
    gate_result:
        Outcome of the broker document gate evaluation.
    outbound_messages:
        Messages that should be sent (e.g. document requests).
    full_details_allowed:
        Whether the full deal package may be sent right now.
    supabase_playbook_slug:
        The ``process_playbooks`` slug in Supabase that governs this
        deal's workflow, if any.
    """

    deal: Deal
    gate_result: GateResult
    outbound_messages: list[str] = field(default_factory=list)
    full_details_allowed: bool = True
    supabase_playbook_slug: Optional[str] = None


def route_inbound_deal(
    deal: Deal,
    *,
    attempt_send_full_details: bool = False,
) -> RoutingDecision:
    """Route a newly received deal through the pipeline.

    Parameters
    ----------
    deal:
        The inbound deal to process.
    attempt_send_full_details:
        Set to ``True`` when the caller wants to send the full deal
        package.  If the gate is not cleared the request will be denied
        and a block-notice message will be generated instead.
    """
    gate = evaluate_gate(deal)
    messages: list[str] = []
    full_ok = may_send_full_details(deal)

    if not gate.cleared:
        deal.advance_to(DealStage.PENDING_DOCUMENTS)

        for action in gate.pending_actions:
            messages.append(
                render_document_request(
                    document_type=action.document_type,
                    broker_name=deal.broker.name if deal.broker else "Broker",
                    urgent=action.urgent,
                    custom_message=action.request_message,
                )
            )

        if attempt_send_full_details and not full_ok:
            messages.append(
                render_full_package_blocked_notice(
                    broker_name=deal.broker.name if deal.broker else "Broker",
                    missing=[a.document_type for a in gate.pending_actions],
                )
            )

        logger.info(
            "Deal %s from broker %s gated — awaiting %s (playbook: %s)",
            deal.deal_id,
            deal.broker.name if deal.broker else "unknown",
            [a.document_type.value for a in gate.pending_actions],
            gate.playbook_slug,
        )
    else:
        if deal.stage == DealStage.PENDING_DOCUMENTS:
            deal.advance_to(DealStage.QUALIFIED)
        logger.info(
            "Deal %s from broker %s — gate cleared, may proceed.",
            deal.deal_id,
            deal.broker.name if deal.broker else "unknown",
        )

    return RoutingDecision(
        deal=deal,
        gate_result=gate,
        outbound_messages=messages,
        full_details_allowed=full_ok,
        supabase_playbook_slug=gate.playbook_slug,
    )


def attempt_release_full_package(deal: Deal) -> RoutingDecision:
    """Try to release the full deal package.

    Call this after documents have been received to check whether the
    gate has cleared and the full package can now be sent.
    """
    return route_inbound_deal(deal, attempt_send_full_details=True)
