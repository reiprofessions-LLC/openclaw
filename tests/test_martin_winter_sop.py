"""Tests for the Martin Winter two-layer SOP.

Validates that:
- Layer 1: Deals from Martin Winter are gated and require POF + LOI.
- Layer 1: Full details are blocked until both documents are received.
- Layer 2: After gate clears, large MF analysis frame is required.
- Layer 2: Analysis metrics (rent comps, occupancy, expense ratios, NOI, cap rate).
- Deals from other brokers are NOT affected by the Martin Winter SOP.
- The Supabase playbook slug and analysis fields are correctly resolved.
- Notification messages are generated correctly.
"""

from __future__ import annotations

import unittest

from miles.config.brokers import (
    MARTIN_WINTER_ANALYSIS_FRAME,
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
from miles.deals.models import (
    AnalysisMetric,
    BrokerContact,
    Deal,
    DealStage,
    DocumentType,
    FrameOfReference,
)
from miles.deals.router import (
    attempt_release_full_package,
    route_inbound_deal,
)
from miles.notifications.templates import (
    render_analysis_complete_notice,
    render_analysis_required_notice,
    render_document_request,
    render_full_package_blocked_notice,
    render_gate_cleared_notice,
)
from miles.workflows.guards import (
    evaluate_gate,
    get_pending_analysis_metrics,
    is_analysis_complete,
    may_send_full_details,
)


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

    def test_martin_winter_has_analysis_frame(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None
        self.assertIsNotNone(sop.analysis_frame)
        self.assertEqual(
            sop.analysis_frame.frame_of_reference,
            FrameOfReference.LARGE_MULTIFAMILY_PROFESSIONAL,
        )

    def test_martin_winter_analysis_metrics(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None and sop.analysis_frame is not None
        metrics = {m for m in sop.analysis_frame.required_metrics}
        self.assertEqual(
            metrics,
            {
                AnalysisMetric.RENT_COMPS,
                AnalysisMetric.OCCUPANCY,
                AnalysisMetric.EXPENSE_RATIOS,
                AnalysisMetric.NOI,
                AnalysisMetric.CAP_RATE,
            },
        )

    def test_martin_winter_analysis_priority_high(self) -> None:
        sop = get_broker_sop("Martin Winter")
        assert sop is not None and sop.analysis_frame is not None
        self.assertEqual(sop.analysis_frame.analysis_priority, "high")


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

    def test_analysis_not_complete_without_metrics(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)
        self.assertFalse(result.analysis_complete)
        self.assertEqual(len(result.analysis_requirements), 5)

    def test_analysis_complete_with_all_metrics(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        for metric in AnalysisMetric:
            deal.set_analysis_value(metric, "test_value")
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)
        self.assertTrue(result.analysis_complete)

    def test_analysis_partial_with_some_metrics(self) -> None:
        deal = self._make_martin_winter_deal()
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        deal.set_analysis_value(AnalysisMetric.RENT_COMPS, "$1200/unit")
        deal.set_analysis_value(AnalysisMetric.NOI, "$500,000")
        result = evaluate_gate(deal)
        self.assertTrue(result.cleared)
        self.assertFalse(result.analysis_complete)
        unsatisfied = [r for r in result.analysis_requirements if not r.satisfied]
        self.assertEqual(len(unsatisfied), 3)

    def test_analysis_frame_none_for_other_brokers(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Jane Doe"),
        )
        result = evaluate_gate(deal)
        self.assertIsNone(result.analysis_frame)
        self.assertTrue(result.analysis_complete)


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

    def test_deal_moves_to_analysis_required_after_docs(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
            stage=DealStage.PENDING_DOCUMENTS,
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = route_inbound_deal(deal)
        self.assertTrue(result.full_details_allowed)
        self.assertEqual(result.deal.stage, DealStage.ANALYSIS_REQUIRED)
        self.assertTrue(result.analysis_required)
        self.assertFalse(result.analysis_complete)

    def test_analysis_required_notice_generated(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
            stage=DealStage.PENDING_DOCUMENTS,
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        result = route_inbound_deal(deal)
        analysis_msgs = [
            m for m in result.outbound_messages if "ANALYSIS REQUIRED" in m
        ]
        self.assertEqual(len(analysis_msgs), 1)
        self.assertIn("large_multifamily_professional", analysis_msgs[0])

    def test_full_package_released_after_docs_and_analysis(self) -> None:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
            stage=DealStage.PENDING_DOCUMENTS,
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        for metric in AnalysisMetric:
            deal.set_analysis_value(metric, "test_value")
        result = attempt_release_full_package(deal)
        self.assertTrue(result.full_details_allowed)
        self.assertTrue(result.analysis_complete)
        self.assertEqual(result.deal.stage, DealStage.QUALIFIED)

    def test_other_broker_deal_passes_through(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Regular Broker"),
        )
        result = route_inbound_deal(deal)
        self.assertTrue(result.full_details_allowed)
        self.assertFalse(result.analysis_required)
        self.assertTrue(result.analysis_complete)
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

    def test_martin_winter_playbook_frame_of_reference(self) -> None:
        pb = get_playbook("martin-winter-pof-loi-gate")
        assert pb is not None
        self.assertEqual(
            pb.frame_of_reference, "large_multifamily_professional"
        )

    def test_martin_winter_playbook_analysis_priority(self) -> None:
        pb = get_playbook("martin-winter-pof-loi-gate")
        assert pb is not None
        self.assertEqual(pb.analysis_priority, "high")


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

    def test_analysis_required_notice(self) -> None:
        msg = render_analysis_required_notice(
            broker_name="Martin Winter",
            frame_label="large_multifamily_professional",
            pending_metrics=["rent_comps", "occupancy", "noi"],
        )
        self.assertIn("ANALYSIS REQUIRED", msg)
        self.assertIn("Martin Winter", msg)
        self.assertIn("large_multifamily_professional", msg)
        self.assertIn("rent_comps", msg)

    def test_analysis_complete_notice(self) -> None:
        msg = render_analysis_complete_notice(
            broker_name="Martin Winter",
            frame_label="large_multifamily_professional",
        )
        self.assertIn("complete", msg.lower())
        self.assertIn("Martin Winter", msg)


class TestAnalysisHelpers(unittest.TestCase):
    """Verify analysis guard helper functions."""

    def _make_gated_deal(self) -> Deal:
        deal = Deal(
            property_address="123 Main St",
            broker=BrokerContact(name="Martin Winter"),
        )
        deal.record_document(DocumentType.PROOF_OF_FUNDS)
        deal.record_document(DocumentType.LETTER_OF_INTENT)
        return deal

    def test_pending_analysis_metrics_all_missing(self) -> None:
        deal = self._make_gated_deal()
        pending = get_pending_analysis_metrics(deal)
        self.assertEqual(len(pending), 5)

    def test_pending_analysis_metrics_partial(self) -> None:
        deal = self._make_gated_deal()
        deal.set_analysis_value(AnalysisMetric.RENT_COMPS, "$1200")
        deal.set_analysis_value(AnalysisMetric.CAP_RATE, "6.5%")
        pending = get_pending_analysis_metrics(deal)
        self.assertEqual(len(pending), 3)
        pending_names = {m for m in pending}
        self.assertNotIn(AnalysisMetric.RENT_COMPS, pending_names)
        self.assertNotIn(AnalysisMetric.CAP_RATE, pending_names)

    def test_pending_analysis_metrics_none_for_other_broker(self) -> None:
        deal = Deal(
            property_address="456 Oak Ave",
            broker=BrokerContact(name="Jane Doe"),
        )
        pending = get_pending_analysis_metrics(deal)
        self.assertEqual(len(pending), 0)

    def test_is_analysis_complete_false(self) -> None:
        deal = self._make_gated_deal()
        self.assertFalse(is_analysis_complete(deal))

    def test_is_analysis_complete_true(self) -> None:
        deal = self._make_gated_deal()
        for metric in AnalysisMetric:
            deal.set_analysis_value(metric, "value")
        self.assertTrue(is_analysis_complete(deal))


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

    def test_martin_winter_prompt_includes_analysis_frame(self) -> None:
        prompt = build_deal_routing_prompt(broker_name="Martin Winter")
        self.assertIn("large_multifamily_professional", prompt)
        self.assertIn("Rent comps", prompt)
        self.assertIn("Occupancy", prompt)
        self.assertIn("Expense ratios", prompt)
        self.assertIn("NOI", prompt)
        self.assertIn("Cap rate", prompt)
        self.assertIn("ANALYSIS_REQUIRED", prompt)

    def test_other_broker_prompt_excludes_martin_winter_sop(self) -> None:
        prompt = build_deal_routing_prompt(broker_name="Other Broker")
        self.assertNotIn("martin-winter-pof-loi-gate", prompt)


if __name__ == "__main__":
    unittest.main()
