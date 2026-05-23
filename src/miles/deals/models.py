"""Data models for the Miles deal pipeline."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class DealStage(enum.Enum):
    """Stages a deal passes through in the pipeline."""

    RECEIVED = "received"
    PENDING_DOCUMENTS = "pending_documents"
    QUALIFIED = "qualified"
    FULL_PACKAGE_SENT = "full_package_sent"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"
    REJECTED = "rejected"


class DocumentType(enum.Enum):
    """Documents that may be required before a deal advances."""

    PROOF_OF_FUNDS = "proof_of_funds"
    LETTER_OF_INTENT = "letter_of_intent"


@dataclass
class BrokerContact:
    """Represents a broker or deal source."""

    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    broker_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Document:
    """A document attached to a deal."""

    doc_type: DocumentType
    received_at: Optional[datetime] = None
    file_url: Optional[str] = None

    @property
    def is_received(self) -> bool:
        return self.received_at is not None


@dataclass
class Deal:
    """A real‑estate deal flowing through the Miles pipeline."""

    deal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    property_address: str = ""
    broker: Optional[BrokerContact] = None
    stage: DealStage = DealStage.RECEIVED
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    documents: dict[DocumentType, Document] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def record_document(
        self, doc_type: DocumentType, file_url: Optional[str] = None
    ) -> None:
        """Mark a required document as received."""
        self.documents[doc_type] = Document(
            doc_type=doc_type,
            received_at=datetime.now(timezone.utc),
            file_url=file_url,
        )
        self.updated_at = datetime.now(timezone.utc)

    def has_document(self, doc_type: DocumentType) -> bool:
        doc = self.documents.get(doc_type)
        return doc is not None and doc.is_received

    def advance_to(self, stage: DealStage) -> None:
        self.stage = stage
        self.updated_at = datetime.now(timezone.utc)
