"""Modelos de dados do Radar Pokémon Brasil."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """Tipos de intenção detectados em menções públicas."""

    BUY_INTENT = "BUY_INTENT"
    SELL_INTENT = "SELL_INTENT"
    PRICE_REFERENCE = "PRICE_REFERENCE"
    DISCUSSION = "DISCUSSION"
    UNKNOWN = "UNKNOWN"


class DataMode(str, Enum):
    """Origem dos dados coletados."""

    LIVE = "live"
    MOCK = "mock"
    MANUAL_IMPORT = "manual_import"
    OPT_IN = "opt_in"


class RadarResult(BaseModel):
    """Um resultado coletado de uma fonte pública."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    platform: str
    card_name_detected: str
    normalized_card_name: str
    title: str = ""
    text_snippet: str = ""
    url: str
    author_or_seller: str = ""
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    intent_type: IntentType = IntentType.UNKNOWN
    intent_score: int = 0
    price: Optional[float] = None
    currency: str = "BRL"
    location: str = ""
    raw_data_json: str = "{}"
    data_mode: DataMode = DataMode.LIVE

    def to_db_row(self) -> dict[str, Any]:
        """Converte o modelo para linha do banco SQLite."""
        return {
            "id": self.id,
            "source": self.source,
            "platform": self.platform,
            "card_name_detected": self.card_name_detected,
            "normalized_card_name": self.normalized_card_name,
            "title": self.title,
            "text_snippet": self.text_snippet,
            "url": self.url,
            "author_or_seller": self.author_or_seller,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "collected_at": self.collected_at.isoformat(),
            "intent_type": self.intent_type.value,
            "intent_score": self.intent_score,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "raw_data_json": self.raw_data_json,
            "data_mode": self.data_mode.value,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "RadarResult":
        """Reconstrói o modelo a partir de uma linha do banco."""
        published = row.get("published_at")
        collected = row.get("collected_at")
        return cls(
            id=row["id"],
            source=row["source"],
            platform=row["platform"],
            card_name_detected=row["card_name_detected"],
            normalized_card_name=row["normalized_card_name"],
            title=row.get("title") or "",
            text_snippet=row.get("text_snippet") or "",
            url=row["url"],
            author_or_seller=row.get("author_or_seller") or "",
            published_at=datetime.fromisoformat(published) if published else None,
            collected_at=(
                datetime.fromisoformat(collected)
                if collected
                else datetime.now(timezone.utc)
            ),
            intent_type=IntentType(row.get("intent_type", "UNKNOWN")),
            intent_score=int(row.get("intent_score") or 0),
            price=row.get("price"),
            currency=row.get("currency") or "BRL",
            location=row.get("location") or "",
            raw_data_json=row.get("raw_data_json") or "{}",
            data_mode=DataMode(row.get("data_mode") or DataMode.LIVE.value),
        )

    def set_raw_data(self, data: Any) -> None:
        """Serializa dados brutos da API para JSON."""
        self.raw_data_json = json.dumps(data, ensure_ascii=False, default=str)


def tag_results(results: list[RadarResult], mode: DataMode) -> list[RadarResult]:
    """Define data_mode em uma lista de resultados."""
    for result in results:
        result.data_mode = mode
    return results
