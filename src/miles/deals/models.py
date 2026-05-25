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
    ANALYSIS_REQUIRED = "analysis_required"
    FULL_PACKAGE_SENT = "full_package_sent"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"
    REJECTED = "rejected"


class DocumentType(enum.Enum):
    """Documents that may be required before a deal advances."""

    PROOF_OF_FUNDS = "proof_of_funds"
    LETTER_OF_INTENT = "letter_of_intent"


class AnalysisMetric(enum.Enum):
    """Metrics required for a deal analysis frame."""

    RENT_COMPS = "rent_comps"
    OCCUPANCY = "occupancy"
    EXPENSE_RATIOS = "expense_ratios"
    NOI = "noi"
    CAP_RATE = "cap_rate"


class FrameOfReference(enum.Enum):
    """Predefined analysis frames that determine how a deal is evaluated."""

    LARGE_MULTIFAMILY_PROFESSIONAL = "large_multifamily_professional"


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
    analysis_data: dict[AnalysisMetric, str] = field(default_factory=dict)
    frame_of_reference: Optional[FrameOfReference] = None
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

    def set_analysis_value(
        self, metric: AnalysisMetric, value: str
    ) -> None:
        """Record an analysis metric value."""
        self.analysis_data[metric] = value
        self.updated_at = datetime.now(timezone.utc)

    def has_analysis_metric(self, metric: AnalysisMetric) -> bool:
        return metric in self.analysis_data and self.analysis_data[metric] != ""

    def advance_to(self, stage: DealStage) -> None:
        self.stage = stage
        self.updated_at = datetime.now(timezone.utc)
