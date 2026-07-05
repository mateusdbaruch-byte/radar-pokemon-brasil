#!/usr/bin/env bash
# Atalho para rodar o Radar Pokémon Brasil (Linux/Mac)
# Uso: ./radar.sh search --mock --limit 5

set -e
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

exec "$PYTHON" -m src "$@"
