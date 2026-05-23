"""Message templates for deal-pipeline notifications."""

from __future__ import annotations

from miles.deals.models import DocumentType

_DOC_LABELS: dict[DocumentType, str] = {
    DocumentType.PROOF_OF_FUNDS: "Proof of Funds (POF)",
    DocumentType.LETTER_OF_INTENT: "Letter of Intent (LOI)",
}


def _label(doc: DocumentType) -> str:
    return _DOC_LABELS.get(doc, doc.value)


def render_document_request(
    document_type: DocumentType,
    broker_name: str,
    urgent: bool = False,
    custom_message: str | None = None,
) -> str:
    """Build a message requesting a specific document from a broker."""
    priority = "URGENT: " if urgent else ""
    body = custom_message or (
        f"Please provide your {_label(document_type)} so we can proceed "
        f"with the deal review."
    )
    return (
        f"{priority}Document Request for {broker_name}\n"
        f"Required: {_label(document_type)}\n\n"
        f"{body}"
    )


def render_full_package_blocked_notice(
    broker_name: str,
    missing: list[DocumentType],
) -> str:
    """Build a notice explaining why the full package cannot be sent."""
    items = ", ".join(_label(d) for d in missing)
    return (
        f"Full deal package BLOCKED for {broker_name}.\n"
        f"Outstanding required documents: {items}.\n\n"
        f"Per operational SOP, no full details, expanded materials, or "
        f"complete deal packages will be released until all required "
        f"documents are received."
    )


def render_gate_cleared_notice(broker_name: str) -> str:
    """Build a confirmation that the gate is now cleared."""
    return (
        f"All required documents received from {broker_name}.\n"
        f"The deal is now cleared to proceed — full package may be sent."
    )
