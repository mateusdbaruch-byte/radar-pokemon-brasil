"""Importação manual de preços — LigaPokemon, MYP Cards, etc."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.models import DataMode, IntentType, RadarResult, tag_results
from src.normalizer import normalize_card_name

REQUIRED_COLUMNS = (
    "source",
    "card_name",
    "price",
    "currency",
    "condition",
    "language",
    "url",
    "seller",
    "collected_at",
)

ALLOWED_SOURCES = frozenset({"liga_pokemon", "myp_cards", "manual", "mercado_livre"})
ALLOWED_CURRENCIES = frozenset({"BRL", "USD", "EUR"})


@dataclass
class ImportValidationError:
    row: int
    column: str
    message: str


@dataclass
class ImportValidationResult:
  valid: bool
  errors: list[ImportValidationError] = field(default_factory=list)
  row_count: int = 0


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_price(value: str) -> float | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace("R$", "").replace(" ", "")
    cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.count(",") == 1 and cleaned.count(".") > 1 else cleaned.replace(",", ".")
    try:
        price = float(cleaned)
        return price if price >= 0 else None
    except ValueError:
        return None


def validate_import_file(path: Path) -> ImportValidationResult:
    """Valida CSV de importação manual."""
    errors: list[ImportValidationError] = []
    if not path.exists():
        return ImportValidationResult(
            valid=False,
            errors=[ImportValidationError(0, "", f"Arquivo não encontrado: {path}")],
        )

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return ImportValidationResult(
                valid=False,
                errors=[ImportValidationError(0, "", "CSV sem cabeçalho")],
            )
        headers = [h.strip() for h in reader.fieldnames]
        for col in REQUIRED_COLUMNS:
            if col not in headers:
                errors.append(
                    ImportValidationError(0, col, f"Coluna obrigatória ausente: {col}")
                )
        if errors:
            return ImportValidationResult(valid=False, errors=errors)

        row_count = 0
        for idx, row in enumerate(reader, start=2):
            row_count += 1
            source = (row.get("source") or "").strip().lower()
            if not source:
                errors.append(ImportValidationError(idx, "source", "source é obrigatório"))
            elif source not in ALLOWED_SOURCES:
                errors.append(
                    ImportValidationError(
                        idx,
                        "source",
                        f"source inválido '{source}' — use: {', '.join(sorted(ALLOWED_SOURCES))}",
                    )
                )

            card_name = (row.get("card_name") or "").strip()
            if not card_name:
                errors.append(ImportValidationError(idx, "card_name", "card_name é obrigatório"))

            price_raw = row.get("price", "")
            price = _parse_price(price_raw)
            if price is None:
                errors.append(
                    ImportValidationError(
                        idx,
                        "price",
                        f"preço inválido: '{price_raw}' (use número, ex: 450.00)",
                    )
                )

            currency = (row.get("currency") or "BRL").strip().upper()
            if currency not in ALLOWED_CURRENCIES:
                errors.append(
                    ImportValidationError(
                        idx,
                        "currency",
                        f"moeda inválida '{currency}' — use BRL, USD ou EUR",
                    )
                )

            url = (row.get("url") or "").strip()
            if not url:
                errors.append(ImportValidationError(idx, "url", "url é obrigatória"))
            elif not url.startswith(("http://", "https://")):
                errors.append(ImportValidationError(idx, "url", "url deve começar com http:// ou https://"))

            collected_raw = row.get("collected_at", "")
            if collected_raw and _parse_date(collected_raw) is None:
                errors.append(
                    ImportValidationError(
                        idx,
                        "collected_at",
                        f"data inválida: '{collected_raw}' (use YYYY-MM-DD)",
                    )
                )

    return ImportValidationResult(valid=len(errors) == 0, errors=errors, row_count=row_count)


def import_prices_from_csv(path: Path) -> list[RadarResult]:
    """Importa CSV validado para RadarResult com data_mode=manual_import."""
    validation = validate_import_file(path)
    if not validation.valid:
        msgs = [f"Linha {e.row} [{e.column}]: {e.message}" for e in validation.errors]
        raise ValueError("CSV inválido:\n" + "\n".join(msgs))

    results: list[RadarResult] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            card_name = row["card_name"].strip()
            condition = (row.get("condition") or "").strip()
            language = (row.get("language") or "").strip()
            seller = (row.get("seller") or "").strip()
            source = row["source"].strip().lower()
            collected = _parse_date(row.get("collected_at", "")) or datetime.now(timezone.utc)
            price = _parse_price(row["price"])
            if price is None:
                continue

            snippet_parts = [f"Preço manual {source}", card_name]
            if condition:
                snippet_parts.append(f"condição: {condition}")
            if language:
                snippet_parts.append(f"idioma: {language}")

            result = RadarResult(
                source=source,
                platform=source,
                card_name_detected=card_name,
                normalized_card_name=normalize_card_name(card_name),
                title=f"{card_name} — {source}",
                text_snippet=" | ".join(snippet_parts),
                url=row["url"].strip(),
                author_or_seller=seller,
                published_at=collected,
                collected_at=collected,
                intent_type=IntentType.PRICE_REFERENCE,
                intent_score=50,
                price=price,
                currency=(row.get("currency") or "BRL").strip().upper(),
                location=condition,
                data_mode=DataMode.MANUAL_IMPORT,
            )
            result.set_raw_data(dict(row))
            results.append(result)

    return tag_results(results, DataMode.MANUAL_IMPORT)
