"""Tests for the Martin Winter POF/LOI gate SOP.

Validates that:
- Deals from Martin Winter are gated and require POF + LOI.
- Full details are blocked until both documents are received.
- Deals from other brokers are NOT affected by the Martin Winter SOP.
- The Supabase playbook slug is correctly resolved.
- Notification messages are generated correctly.
"""

from __future__ import annotations

import unittest

from miles.config.brokers import (
    MARTIN_WINTER_SOP,
    get_broker_sop,
    list_broker_sops,
    register_broker_sop,
)
from miles.config.prompts import build_deal_routing_prompt
from miles.config.supabase import (
    MARTIN_WINTER_PLAYBOOK,
    SUPABASE_PROJECT_ID,
    get_playbook,
)
from miles.deals.models import BrokerContact, Deal, DealStage, DocumentType
from miles.deals.router import (
    attempt_release_full_package,
    route_inbound_deal,
)
from miles.notifications.templates import (
    render_document_request,
    render_full_package_blocked_notice,
    render_gate_cleared_notice,
)
from miles.workflows.guards import evaluate_gate, may_send_full_details


class TestBrokerSOPRegistry(unittest.TestCase):
    """Verify the broker SOP registry works correctly."""

    def test_martin_winter_sop_registered(self) -> None:
        sop = get_broker_sop("Martin Winter")
        self.assertIsNotNone(sop)
        self.assertEqual(sop.broker_name, "Martin Winter")

    def test_case_insensitive_lookup(self) -> None:
        for variant in ("martin winter", "MARTIN WINTER", " Martin Winter "):
            sop = get_broker_sop(variant)
            self.assertIsNotNone(sop, f"Failed for variant: {variant!r}")

    def test_unknown_broker_returns_none(self) -> None:
        self.assertIsNone(get_broker_sop("Jane Doe"))

    def test_martin_winter_requires_pof_and_loi(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None
        doc_types = {r.document_type for r in sop.gate_documents}
        self.assertIn(DocumentType.PROOF_OF_FUNDS, doc_types)
        self.assertIn(DocumentType.LETTER_OF_INTENT, doc_types)

    def test_martin_winter_gate_is_urgent(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None
        for req in sop.gate_documents:
            self.assertTrue(req.urgent, f"{req.document_type} should be urgent")

    def test_martin_winter_blocks_full_details(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None
        self.assertTrue(sop.block_full_details_until_gate_cleared)

    def test_list_broker_sops_includes_martin_winter(self) -> None:
        sops = list_broker_sops()
        names = [s.broker_name for s in sops]
        self.assertIn("Martin Winter", names)


class TestGateEvaluation(unittest.TestCase):
    """Verify the document gate logic."""

    def _make_martin_winter_deal(self) -> Deal:
        return Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )

    def test_gate_not_cleared_without_documents(self) -> None:
        deal = self._make_martin_winter_deal()
        result = evaluate_gate(deal)
        self.assertFalse(result.cleared)
        self.assertEqual(len(result.pending_actions), 2)

    def test_gate_not_cleared_with_only_pof(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        result = evaluate_gate(deal)
        self.assertFalse(result.cleared)
        self.assertEqual(len(result.pending_actions), 1)
        self.assertEqual(
            result.pending_actions[0].document_type,
            DocumentType.LETTER_OF_INTENT,
        )

    def test_gate_not_cleared_with_only_loi(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = evaluate_gate(deal)
        self.assertFalse(result.cleared)
        self.assertEqual(len(result.pending_actions), 1)
        self.assertEqual(
            result.pending_actions[0].document_type,
            DocumentType.PROOF_OF_FUNDS,
        )

    def test_gate_cleared_with_both_documents(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)
        self.assertEqual(len(result.pending_actions), 0)

    def test_gate_auto_cleared_for_other_brokers(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Jane Doe"),
        )
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)

    def test_gate_auto_cleared_when_no_broker(self) -> None:
        deal = Deal(property_address="789 Pine Rd")
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)

    def test_playbook_slug_resolved_for_martin_winter(self) -> None:
        deal = self._make_martin_winter_deal()
        result = evaluate_gate(deal)
        self.assertEqual(result.playbook_slug, "martin-winter-pof-loi-gate")

    def test_playbook_slug_none_for_other_brokers(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Jane Doe"),
        )
        result = evaluate_gate(deal)
        self.assertIsNone(result.playbook_slug)


class TestMaySendFullDetails(unittest.TestCase):
    """Verify the full-details permission check."""

    def test_blocked_for_martin_winter_without_docs(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        self.assertFalse(may_send_full_details(deal))

    def test_blocked_for_martin_winter_with_partial_docs(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        self.assertFalse(may_send_full_details(deal))

    def test_allowed_for_martin_winter_with_both_docs(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        self.assertTrue(may_send_full_details(deal))

    def test_allowed_for_other_brokers_without_docs(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Some Other Broker"),
        )
        self.assertTrue(may_send_full_details(deal))


class TestDealRouter(unittest.TestCase):
    """Verify the deal intake router."""

    def test_martin_winter_deal_moves_to_pending(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        result = route_inbound_deal(deal)
        self.assertEqual(result.deal.stage, DealStage.PENDING_DOCUMENTS)
        self.assertFalse(result.full_details_allowed)
        self.assertGreater(len(result.outbound_messages), 0)
        self.assertEqual(
            result.supabase_playbook_slug, "martin-winter-pof-loi-gate"
        )

    def test_martin_winter_generates_urgent_requests(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        result = route_inbound_deal(deal)
        urgent_count = sum(
            1 for m in result.outbound_messages if m.startswith("URGENT:")
        )
        self.assertEqual(urgent_count, 2)

    def test_full_package_blocked_when_gate_not_cleared(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        result = route_inbound_deal(deal, attempt_send_full_details=True)
        self.assertFalse(result.full_details_allowed)
        blocked_msgs = [
            m for m in result.outbound_messages if "BLOCKED" in m
        ]
        self.assertGreater(len(blocked_msgs), 0)

    def test_full_package_released_after_both_docs(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
            stage=DealStage.PENDING_DOCUMENTS,
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = attempt_release_full_package(deal)
        self.assertTrue(result.full_details_allowed)
        self.assertEqual(result.deal.stage, DealStage.QUALIFIED)

    def test_other_broker_deal_passes_through(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Regular Broker"),
        )
        result = route_inbound_deal(deal)
        self.assertTrue(result.full_details_allowed)
        self.assertEqual(len(result.outbound_messages), 0)
        self.assertIsNone(result.supabase_playbook_slug)


class TestSupabasePlaybook(unittest.TestCase):
    """Verify Supabase playbook references."""

    def test_project_id(self) -> None:
        self.assertEqual(SUPABASE_PROJECT_ID, "egpqhzubdeklzstzdmtt")

    def test_martin_winter_playbook_exists(self) -> None:
        pb = get_playbook("martin-winter-pof-loi-gate")
        self.assertIsNotNone(pb)
        self.assertEqual(pb.name, "Martin Winter POF/LOI Gate")

    def test_martin_winter_playbook_slug(self) -> None:
        self.assertEqual(
            MARTIN_WINTER_PLAYBOOK.slug, "martin-winter-pof-loi-gate"
        )


class TestNotificationTemplates(unittest.TestCase):
    """Verify notification message rendering."""

    def test_urgent_document_request(self) -> None:
        msg = render_document_request(
            document_type=DocumentType.PROOF_OF_FUNDS,
            broker_name="Martin Winter",
            urgent=True,
        )
        self.assertIn("URGENT:", msg)
        self.assertIn("Martin Winter", msg)
        self.assertIn("Proof of Funds", msg)

    def test_blocked_notice_lists_missing_docs(self) -> None:
        msg = render_full_package_blocked_notice(
            broker_name="Martin Winter",
            missing=[DocumentType.PROOF_OF_FUNDS, DocumentType.LETTER_OF_INTENT],
        )
        self.assertIn("BLOCKED", msg)
        self.assertIn("Proof of Funds", msg)
        self.assertIn("Letter of Intent", msg)

    def test_gate_cleared_notice(self) -> None:
        msg = render_gate_cleared_notice("Martin Winter")
        self.assertIn("cleared", msg.lower())
        self.assertIn("Martin Winter", msg)


class TestPrompts(unittest.TestCase):
    """Verify AI prompt assembly."""

    def test_default_prompt_has_system_instructions(self) -> None:
        prompt = build_deal_routing_prompt()
        self.assertIn("Miles", prompt)
        self.assertIn("gate requirements", prompt.lower())

    def test_martin_winter_prompt_includes_specific_sop(self) -> None:
        prompt = build_deal_routing_prompt(broker_name="Martin Winter")
        self.assertIn("martin-winter-pof-loi-gate", prompt)
        self.assertIn("Proof of Funds", prompt)
        self.assertIn("Letter of Intent", prompt)
        self.assertIn("PENDING_DOCUMENTS", prompt)

    def test_other_broker_prompt_excludes_martin_winter_sop(self) -> None:
        prompt = build_deal_routing_prompt(broker_name="Other Broker")
        self.assertNotIn("martin-winter-pof-loi-gate", prompt)


if __name__ == "__main__":
    unittest.main()
