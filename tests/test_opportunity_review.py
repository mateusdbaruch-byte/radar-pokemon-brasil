"""Testes de revisão humana e validação de qualidade."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.opportunity_db import (
    clear_opportunity_data,
    count_domains_by_review,
    count_human_reviews,
    count_unreviewed_opportunities,
    export_review_csv,
    fetch_opportunities,
    mark_opportunity_review,
    resolve_opportunity_index,
    save_opportunity,
)
from src.opportunity_models import HumanReview, Opportunity, OpportunityType
from src.opportunity_quality import extract_domain
from src.opportunity_reporting import display_precision_report, display_quality_report
from src.models import DataMode
from rich.console import Console


@pytest.fixture
def review_db(tmp_path):
    db = tmp_path / "review.db"
    clear_opportunity_data(db)
    return db


def _make_opp(
    card: str,
    url: str,
    score: int = 80,
    opp_type: OpportunityType = OpportunityType.BUYER_DEMAND,
) -> Opportunity:
    return Opportunity(
        opportunity_type=opp_type,
        source="web_search",
        platform="serpapi",
        card_name_detected=card,
        normalized_card_name=card,
        evidence_text=f"Procuro {card} Pokémon TCG",
        url=url,
        opportunity_score=score,
        confidence_score=75,
        data_mode=DataMode.LIVE,
        why_saved="buyer intent + card match",
    )


class TestDomainField:
    def test_domain_populated_on_save(self, review_db):
        opp = _make_opp("Charizard", "https://www.mercadolivre.com.br/item/123")
        save_opportunity(opp, review_db)
        saved = fetch_opportunities(review_db)[0]
        assert saved.domain == "mercadolivre.com.br"

    def test_extract_domain_helper(self):
        assert extract_domain("https://www.olx.com.br/anuncio") == "olx.com.br"


class TestHumanReview:
    def test_mark_by_index(self, review_db):
        save_opportunity(_make_opp("Charizard", "https://a.com/1", score=90), review_db)
        save_opportunity(_make_opp("Umbreon", "https://b.com/2", score=70), review_db)

        opp = resolve_opportunity_index(1, review_db)
        assert opp is not None
        assert opp.normalized_card_name == "Charizard"

        mark_opportunity_review(opp.id, HumanReview.RELEVANT.value, "bom lead", review_db)
        reviews = count_human_reviews(review_db)
        assert reviews["relevant"] == 1
        assert count_unreviewed_opportunities(review_db) == 1

    def test_mark_irrelevant_and_precision_domains(self, review_db):
        save_opportunity(
            _make_opp("Mew", "https://dicio.com.br/mew", score=60),
            review_db,
        )
        opp = resolve_opportunity_index(1, review_db)
        mark_opportunity_review(opp.id, HumanReview.IRRELEVANT.value, db_path=review_db)

        bad = count_domains_by_review("irrelevant", review_db)
        assert "dicio.com.br" in bad

    def test_resolve_invalid_index(self, review_db):
        assert resolve_opportunity_index(0, review_db) is None
        assert resolve_opportunity_index(99, review_db) is None


class TestExportReviewCsv:
    def test_export_columns(self, review_db, tmp_path):
        opp = _make_opp("Charizard", "https://example.com/x")
        save_opportunity(opp, review_db)
        resolved = resolve_opportunity_index(1, review_db)
        mark_opportunity_review(
            resolved.id,
            HumanReview.MAYBE.value,
            "incerto",
            review_db,
        )

        out = tmp_path / "opportunity_review.csv"
        count = export_review_csv(out, review_db)
        assert count == 1
        content = out.read_text(encoding="utf-8")
        assert "id,card,opportunity_type" in content
        assert "Charizard" in content
        assert "maybe" in content


class TestReportingSmoke:
    def test_precision_report_empty(self, review_db):
        console = Console(file=open("/dev/null", "w"))
        display_precision_report(console)

    def test_quality_report_with_review(self, review_db):
        save_opportunity(_make_opp("Charizard", "https://a.com/1"), review_db)
        opp = resolve_opportunity_index(1, review_db)
        mark_opportunity_review(opp.id, HumanReview.RELEVANT.value, db_path=review_db)
        console = Console(file=open("/dev/null", "w"))
        display_quality_report(console)
