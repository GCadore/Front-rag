#!/usr/bin/env bash
# Deploy do LLM + API no Modal. Uso: ./scripts/deploy.sh [--api-only] [--check]
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/deploy_modal.py "$@"
