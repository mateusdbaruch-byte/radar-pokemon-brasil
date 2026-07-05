"""Caminhos do projeto — sempre relativos à raiz, independente do diretório atual."""

from __future__ import annotations

from pathlib import Path

# Raiz do projeto (pasta que contém src/, config/, data/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_CARDS = CONFIG_DIR / "cards.yml"
DEFAULT_WATCHLIST = CONFIG_DIR / "watchlist.yml"
CARD_ALIASES = CONFIG_DIR / "card_aliases.yml"
NON_CARD_TERMS = CONFIG_DIR / "non_card_terms.yml"
BLOCKED_DOMAINS = CONFIG_DIR / "blocked_domains.yml"
PRIORITY_DOMAINS = CONFIG_DIR / "priority_domains.yml"
SEARCH_PROFILES = CONFIG_DIR / "search_profiles.yml"
DOMAIN_GROUPS = CONFIG_DIR / "domain_groups.yml"
TCG_VOCABULARY = CONFIG_DIR / "tcg_vocabulary.yml"
COLLECTION_ALIASES = CONFIG_DIR / "collection_aliases.yml"
QUERY_TEMPLATES = CONFIG_DIR / "query_templates.yml"
DEFAULT_KEYWORDS = CONFIG_DIR / "keywords.yml"
DEFAULT_SOURCES = CONFIG_DIR / "sources.yml"
DEFAULT_DB = DATA_DIR / "radar.db"
DEFAULT_CSV = DATA_DIR / "radar_results.csv"
IMPORTS_DIR = DATA_DIR / "imports"
DEFAULT_MANUAL_IMPORT = IMPORTS_DIR / "manual_prices_example.csv"


def ensure_data_dir() -> Path:
    """Garante que a pasta data/ existe."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
