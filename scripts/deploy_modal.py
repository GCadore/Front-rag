#!/usr/bin/env python
"""Deploy do LLM (vLLM + Qwen3.5-9B) e da API no Modal; grava a URL da API no .env.local.

    python scripts/deploy_modal.py            # LLM + API
    python scripts/deploy_modal.py --api-only # só a API (mudou código do backend)
    python scripts/deploy_modal.py --check    # depois do deploy, chama /health (acorda a API: ~1-2 min)
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

from _common import API_APP, ENV_LOCAL, LLM_APP, ensure_modal_login, read_env, run, update_env


def web_url(app: str, function: str) -> str:
    import modal

    return modal.Function.from_name(app, function).get_web_url()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-only", action="store_true")
    ap.add_argument("--llm-only", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    ensure_modal_login()

    if not args.api_only:
        run(["deploy", "modal/llm_qwen.py"])
    if not args.llm_only:
        run(["deploy", "backend/modal_app.py"])

    llm_url = web_url(LLM_APP, "serve")
    api_url = web_url(API_APP, "fastapi_app").rstrip("/")
    update_env({"RAG_API_URL": api_url})
    print("\nPronto!")
    print(f"  API (RAG_API_URL): {api_url}")
    print(f"  LLM (OpenAI):      {llm_url.rstrip('/')}/v1")
    print(f"  RAG_API_URL gravado em {ENV_LOCAL.name}. Agora: npm install && npm run dev")

    if args.check:
        key = read_env().get("RAG_API_KEY", "")
        t0 = time.time()
        req = urllib.request.Request(f"{api_url}/health", headers={"x-api-key": key})
        with urllib.request.urlopen(req, timeout=600) as resp:
            print(f"  /health em {time.time() - t0:.0f}s:", json.loads(resp.read()))


if __name__ == "__main__":
    main()
