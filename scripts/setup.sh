#!/usr/bin/env bash
# Setup do Modal (1x por conta). Uso: ./scripts/setup.sh [--skip-llm] ...
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/setup_modal.py "$@"
