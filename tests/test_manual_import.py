"""Testes de importação manual de preços."""

from pathlib import Path

import pytest

from src.manual_import import import_prices_from_csv, validate_import_file
from src.models import DataMode


SAMPLE_CSV = """source,card_name,price,currency,condition,language,url,seller,collected_at
liga_pokemon,Charizard,450.00,BRL,near_mint,pt-BR,https://example.com/c1,Loja,2026-07-01
myp_cards,Pikachu,89.90,BRL,mint,pt-BR,https://example.com/c2,,2026-07-02
"""


class TestManualImport:
    def test_validate_valid_csv(self, tmp_path: Path):
        path = tmp_path / "prices.csv"
        path.write_text(SAMPLE_CSV, encoding="utf-8")
        result = validate_import_file(path)
        assert result.valid is True
        assert result.row_count == 2

    def test_validate_missing_column(self, tmp_path: Path):
        path = tmp_path / "bad.csv"
        path.write_text("source,card_name\nliga_pokemon,Charizard\n", encoding="utf-8")
        result = validate_import_file(path)
        assert result.valid is False
        assert any(e.column == "price" for e in result.errors)

    def test_validate_bad_price(self, tmp_path: Path):
        path = tmp_path / "bad.csv"
        path.write_text(
            "source,card_name,price,currency,condition,language,url,seller,collected_at\n"
            "liga_pokemon,Charizard,abc,BRL,mint,pt,https://x.com,,2026-07-01\n",
            encoding="utf-8",
        )
        result = validate_import_file(path)
        assert result.valid is False

    def test_import_prices(self, tmp_path: Path):
        path = tmp_path / "prices.csv"
        path.write_text(SAMPLE_CSV, encoding="utf-8")
        results = import_prices_from_csv(path)
        assert len(results) == 2
        assert all(r.data_mode == DataMode.MANUAL_IMPORT for r in results)
        assert results[0].price == 450.0
