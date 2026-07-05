"""Testes do comando setup-env."""

from pathlib import Path
from io import StringIO
from unittest.mock import patch

from rich.console import Console

from src.setup_env import run_setup_env


class TestSetupEnv:
    def test_creates_env_from_example(self, tmp_path: Path):
        example = tmp_path / ".env.example"
        example.write_text("REDDIT_CLIENT_ID=\n", encoding="utf-8")

        output = StringIO()
        console = Console(file=output, width=120, force_terminal=True)

        with patch("src.setup_env.PROJECT_ROOT", tmp_path):
            path = run_setup_env(console)

        assert path.exists()
        assert (tmp_path / ".env").exists()
