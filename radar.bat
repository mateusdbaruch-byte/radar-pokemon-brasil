@echo off
REM Atalho para rodar o Radar Pokemon Brasil (Windows)
REM Uso: radar.bat search --mock --limit 5

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m src %*
) else if exist "py" (
    py -3 -m src %*
) else (
    python -m src %*
)
