"""Modelos do Opportunity Radar."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.models import DataMode


class OpportunityType(str, Enum):
    BUYER_INTENT = "buyer_intent"
    SELLER_INTENT = "seller_intent"
    WISHLIST_LEAD = "wishlist_lead"
    MARKETPLACE_LISTING = "marketplace_listing"
    WEB_SIGNAL = "web_signal"
    DISCUSSION = "discussion"
    BUYER_DEMAND = "buyer_demand"
    HIGH_INTENT_LEAD = "high_intent_lead"
    DISCUSSION_SIGNAL = "discussion_signal"
    SELLER_SUPPLY = "seller_supply"
    URGENT_SALE = "urgent_sale"
    UNDERPRICED_LISTING = "underpriced_listing"
    ARBITRAGE_SIGNAL = "arbitrage_signal"
    PRICE_REFERENCE = "price_reference"
    SUPPLY_SIGNAL = "supply_signal"


class OpportunityStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class HumanReview(str, Enum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    MAYBE = "maybe"


class RejectedReview(str, Enum):
    FALSE_NEGATIVE = "false_negative"
    CORRECT_REJECTION = "correct_rejection"


class Opportunity(BaseModel):
    """Oportunidade detectada pelo radar."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    opportunity_type: OpportunityType = OpportunityType.WEB_SIGNAL
    source: str
    platform: str
    card_name_detected: str
    normalized_card_name: str
    evidence_text: str = ""
    url: str = ""
    author_or_seller: str = ""
    price: Optional[float] = None
    currency: str = "BRL"
    intent_score: int = 0
    urgency_score: int = 0
    opportunity_score: int = 0
    confidence_score: int = 0
    data_mode: DataMode = DataMode.LIVE
    status: OpportunityStatus = OpportunityStatus.NEW
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data_json: str = "{}"
    recommended_action: str = ""
    why_saved: str = ""
    collection_detected: str = ""
    rarity_detected: str = ""
    condition_detected: str = ""
    grading_detected: str = ""
    language_detected: str = ""
    market_jargon_detected: str = ""
    negative_context_detected: str = ""
    domain: str = ""
    human_review: str = ""
    human_review_notes: str = ""
    reviewed_at: Optional[datetime] = None

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opportunity_type": self.opportunity_type.value,
            "source": self.source,
            "platform": self.platform,
            "card_name_detected": self.card_name_detected,
            "normalized_card_name": self.normalized_card_name,
            "evidence_text": self.evidence_text,
            "url": self.url,
            "author_or_seller": self.author_or_seller,
            "price": self.price,
            "currency": self.currency,
            "intent_score": self.intent_score,
            "urgency_score": self.urgency_score,
            "opportunity_score": self.opportunity_score,
            "confidence_score": self.confidence_score,
            "data_mode": self.data_mode.value,
            "status": self.status.value,
            "collected_at": self.collected_at.isoformat(),
            "raw_data_json": self.raw_data_json,
            "recommended_action": self.recommended_action,
            "why_saved": self.why_saved,
            "collection_detected": self.collection_detected,
            "rarity_detected": self.rarity_detected,
            "condition_detected": self.condition_detected,
            "grading_detected": self.grading_detected,
            "language_detected": self.language_detected,
            "market_jargon_detected": self.market_jargon_detected,
            "negative_context_detected": self.negative_context_detected,
            "domain": self.domain,
            "human_review": self.human_review,
            "human_review_notes": self.human_review_notes,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> Opportunity:
        collected = row.get("collected_at")
        return cls(
            id=row["id"],
            opportunity_type=OpportunityType(row.get("opportunity_type", "web_signal")),
            source=row["source"],
            platform=row["platform"],
            card_name_detected=row["card_name_detected"],
            normalized_card_name=row["normalized_card_name"],
            evidence_text=row.get("evidence_text") or "",
            url=row.get("url") or "",
            author_or_seller=row.get("author_or_seller") or "",
            price=row.get("price"),
            currency=row.get("currency") or "BRL",
            intent_score=int(row.get("intent_score") or 0),
            urgency_score=int(row.get("urgency_score") or 0),
            opportunity_score=int(row.get("opportunity_score") or 0),
            confidence_score=int(row.get("confidence_score") or 0),
            data_mode=DataMode(row.get("data_mode") or DataMode.LIVE.value),
            status=OpportunityStatus(row.get("status") or OpportunityStatus.NEW.value),
            collected_at=(
                datetime.fromisoformat(collected)
                if collected
                else datetime.now(timezone.utc)
            ),
            raw_data_json=row.get("raw_data_json") or "{}",
            recommended_action=row.get("recommended_action") or "",
            why_saved=row.get("why_saved") or "",
            collection_detected=row.get("collection_detected") or "",
            rarity_detected=row.get("rarity_detected") or "",
            condition_detected=row.get("condition_detected") or "",
            grading_detected=row.get("grading_detected") or "",
            language_detected=row.get("language_detected") or "",
            market_jargon_detected=row.get("market_jargon_detected") or "",
            negative_context_detected=row.get("negative_context_detected") or "",
            domain=row.get("domain") or "",
            human_review=row.get("human_review") or "",
            human_review_notes=row.get("human_review_notes") or "",
            reviewed_at=(
                datetime.fromisoformat(row["reviewed_at"])
                if row.get("reviewed_at")
                else None
            ),
        )

    def set_raw_data(self, data: Any) -> None:
        self.raw_data_json = json.dumps(data, ensure_ascii=False, default=str)


class WishlistLead(BaseModel):
    """Lead opt-in da lista de desejos."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    contact: str = ""
    card_name: str
    collection: str = ""
    language: str = "pt-BR"
    condition: str = ""
    max_price: Optional[float] = None
    urgency: str = "media"
    notes: str = ""
    source: str = "manual"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "contact": self.contact,
            "card_name": self.card_name,
            "collection": self.collection,
            "language": self.language,
            "condition": self.condition,
            "max_price": self.max_price,
            "urgency": self.urgency,
            "notes": self.notes,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> WishlistLead:
        created = row.get("created_at")
        return cls(
            id=row["id"],
            name=row["name"],
            contact=row.get("contact") or "",
            card_name=row["card_name"],
            collection=row.get("collection") or "",
            language=row.get("language") or "pt-BR",
            condition=row.get("condition") or "",
            max_price=row.get("max_price"),
            urgency=row.get("urgency") or "media",
            notes=row.get("notes") or "",
            source=row.get("source") or "manual",
            created_at=(
                datetime.fromisoformat(created)
                if created
                else datetime.now(timezone.utc)
            ),
        )
