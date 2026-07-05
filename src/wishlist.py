"""Lista de desejos — cadastro e importação opt-in."""

from __future__ import annotations

import csv
from pathlib import Path

from src.opportunity_models import WishlistLead
from src.opportunity_db import save_wishlist_leads


REQUIRED_COLUMNS = (
    "name",
    "contact",
    "card_name",
    "collection",
    "language",
    "condition",
    "max_price",
    "urgency",
    "notes",
    "source",
)


def _parse_price(value: str) -> float | None:
    if not value or not str(value).strip():
        return None
    cleaned = str(value).strip().replace("R$", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def validate_wishlist_csv(path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not path.exists():
        return False, [f"Arquivo não encontrado: {path}"]

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return False, ["CSV sem cabeçalho"]
        headers = {h.strip() for h in reader.fieldnames}
        for col in ("name", "card_name"):
            if col not in headers:
                errors.append(f"Coluna obrigatória ausente: {col}")
        if errors:
            return False, errors

        for idx, row in enumerate(reader, start=2):
            if not (row.get("name") or "").strip():
                errors.append(f"Linha {idx}: name obrigatório")
            if not (row.get("card_name") or "").strip():
                errors.append(f"Linha {idx}: card_name obrigatório")
            price_raw = row.get("max_price", "")
            if price_raw and _parse_price(price_raw) is None:
                errors.append(f"Linha {idx}: max_price inválido")

    return len(errors) == 0, errors


def import_wishlist_csv(path: Path) -> list[WishlistLead]:
    ok, errors = validate_wishlist_csv(path)
    if not ok:
        raise ValueError("\n".join(errors))

    leads: list[WishlistLead] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(WishlistLead(
                name=row["name"].strip(),
                contact=(row.get("contact") or "").strip(),
                card_name=row["card_name"].strip(),
                collection=(row.get("collection") or "").strip(),
                language=(row.get("language") or "pt-BR").strip(),
                condition=(row.get("condition") or "").strip(),
                max_price=_parse_price(row.get("max_price", "")),
                urgency=(row.get("urgency") or "media").strip(),
                notes=(row.get("notes") or "").strip(),
                source=(row.get("source") or "import").strip(),
            ))
    save_wishlist_leads(leads)
    return leads
