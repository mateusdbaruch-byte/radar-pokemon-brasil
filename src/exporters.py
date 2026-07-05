"""Exportação de resultados para CSV e outros formatos."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.database import fetch_all
from src.models import RadarResult

DEFAULT_CSV_PATH = Path("data/radar_results.csv")


def results_to_dataframe(results: list[RadarResult]) -> pd.DataFrame:
    """Converte lista de RadarResult em DataFrame pandas."""
    rows = [r.to_db_row() for r in results]
    return pd.DataFrame(rows)


def export_to_csv(
    output_path: Path | str = DEFAULT_CSV_PATH,
    db_path: Path | str = "data/radar.db",
) -> Path:
    """
    Exporta todos os resultados do SQLite para CSV.

    Retorna o caminho do arquivo gerado.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    results = fetch_all(db_path)
    df = results_to_dataframe(results)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def export_results_list(
    results: list[RadarResult],
    output_path: Path | str = DEFAULT_CSV_PATH,
) -> Path:
    """Exporta uma lista de resultados diretamente para CSV."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = results_to_dataframe(results)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
