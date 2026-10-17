# Deploy do LLM + API no Modal. Uso: powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1 [--api-only] [--check]
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONIOENCODING = "utf-8"
python scripts/deploy_modal.py @args
