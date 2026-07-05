"""Testes de avisos de data_mode no relatório."""

from datetime import datetime, timezone
from io import StringIO

from rich.console import Console

from src.models import DataMode, RadarResult
from src.reporting import display_data_mode_summary


def _make_result(mode: DataMode) -> RadarResult:
    return RadarResult(
        source="reddit",
        platform="reddit",
        card_name_detected="Charizard",
        normalized_card_name="Charizard",
        url="https://example.com",
        data_mode=mode,
        collected_at=datetime.now(timezone.utc),
    )


class TestDataModeReport:
    def test_shows_mock_warning(self):
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=True)
        display_data_mode_summary(console, [_make_result(DataMode.MOCK)])
        text = output.getvalue().replace("\n", " ")
        assert "DADOS SIMULADOS" in text
        assert "decisão de mercado" in text

    def test_shows_live_counts(self):
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=True)
        display_data_mode_summary(
            console,
            [_make_result(DataMode.LIVE), _make_result(DataMode.LIVE)],
        )
        text = output.getvalue()
        assert "live" in text
        assert "Todos os dados são reais" in text
