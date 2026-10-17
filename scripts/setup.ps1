# Setup do Modal (1x por conta). Uso: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [--skip-llm] ...
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONIOENCODING = "utf-8"
python scripts/setup_modal.py @args
