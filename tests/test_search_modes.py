"""Testes dos modos de busca."""

import pytest

from src.search_modes import SearchMode, resolve_search_mode


class TestResolveSearchMode:
    def test_default_is_allow_mock(self):
        assert resolve_search_mode() == SearchMode.ALLOW_MOCK

    def test_live_only(self):
        assert resolve_search_mode(live_only=True) == SearchMode.LIVE_ONLY

    def test_allow_mock_explicit(self):
        assert resolve_search_mode(allow_mock=True) == SearchMode.ALLOW_MOCK

    def test_mock_only(self):
        assert resolve_search_mode(mock_only=True) == SearchMode.MOCK_ONLY

    def test_mutually_exclusive_raises(self):
        with pytest.raises(ValueError, match="apenas um modo"):
            resolve_search_mode(live_only=True, mock_only=True)
