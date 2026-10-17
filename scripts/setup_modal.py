#!/usr/bin/env python
"""Setup do Modal (1x por conta): secret com as chaves, Volume com os índices e pesos do LLM.

    python scripts/setup_modal.py                 # tudo
    python scripts/setup_modal.py --only base,logico   # só alguns índices
    python scripts/setup_modal.py --skip-llm      # sem pré-baixar o Qwen
    python scripts/setup_modal.py --rotate-keys   # gera chaves novas (troca no Modal e no .env.local)

Pré-requisitos: pip install modal   e   modal setup   (login na SUA conta).
Os nomes (Volume, secret, apps) vêm de variáveis de ambiente; ver COMO_RODAR.md.
"""
from __future__ import annotations

import argparse
import secrets
import time

from _common import ENV_LOCAL, SECRET, VOLUME, ensure_modal_login, read_env, run, secret_exists, update_env


def ensure_secret(rotate: bool) -> None:
    has_local_key = read_env().get("RAG_API_KEY", "troque-isto") not in ("", "troque-isto")
    if secret_exists(SECRET) and not rotate:
        print(f"Secret '{SECRET}' já existe.")
        if not has_local_key:
            print("  Atenção: o .env.local não tem o RAG_API_KEY desse secret (o Modal não mostra o valor de\n"
                  "  um secret depois de criado). Peça a chave pra quem criou o secret ou rode de novo com\n"
                  "  --rotate-keys pra gerar chaves novas (quem usava a chave antiga precisa da nova).")
        return
    rag_key, llm_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    print(f"> modal secret create {SECRET} RAG_API_KEY=*** LLM_API_KEY=***")
    run(["secret", "create", "--force", SECRET, f"RAG_API_KEY={rag_key}", f"LLM_API_KEY={llm_key}"], show=False, capture=True)
    update_env({"RAG_API_KEY": rag_key, "MOCK_API": "false"})
    print(f"Secret '{SECRET}' criado; RAG_API_KEY gravado em {ENV_LOCAL.name}.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="índices separados por vírgula: base,enxuto,logico,base_extras")
    ap.add_argument("--force", action="store_true", help="baixa os índices de novo mesmo se já existirem")
    ap.add_argument("--skip-data", action="store_true")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--rotate-keys", action="store_true")
    args = ap.parse_args()

    ensure_modal_login()
    t0 = time.time()
    print("\n== 1/3 Secret com as chaves")
    ensure_secret(args.rotate_keys)

    if not args.skip_data:
        print(f"\n== 2/3 Volume '{VOLUME}' com os índices (Google Drive -> Modal, ~5-10 min na 1a vez)")
        cmd = ["run", "backend/modal_app.py::setup"]
        if args.only:
            cmd += ["--only", args.only]
        if args.force:
            cmd += ["--force"]
        run(cmd)

    if not args.skip_llm:
        print("\n== 3/3 Pesos do LLM no Volume (sem GPU, ~3-5 min na 1a vez)")
        run(["run", "modal/llm_qwen.py::download_model"])

    print(f"\nSetup concluído em {(time.time() - t0) / 60:.1f} min. Agora:  python scripts/deploy_modal.py")


if __name__ == "__main__":
    main()
