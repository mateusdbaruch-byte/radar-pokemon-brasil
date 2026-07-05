"""Modos de execução do comando search."""

from __future__ import annotations

from enum import Enum


class SearchMode(str, Enum):
    LIVE_ONLY = "live-only"
    ALLOW_MOCK = "allow-mock"
    MOCK_ONLY = "mock-only"


def resolve_search_mode(
    live_only: bool = False,
    allow_mock: bool = False,
    mock_only: bool = False,
) -> SearchMode:
    """Resolve flags da CLI em um único modo de busca."""
    flags = sum([live_only, allow_mock, mock_only])
    if flags > 1:
        raise ValueError("Use apenas um modo: --live-only, --allow-mock ou --mock-only")
    if mock_only:
        return SearchMode.MOCK_ONLY
    if live_only:
        return SearchMode.LIVE_ONLY
    if allow_mock:
        return SearchMode.ALLOW_MOCK
    # Padrão: allow-mock (compatível com fallback automático anterior)
    return SearchMode.ALLOW_MOCK
