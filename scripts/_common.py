"""Funções compartilhadas pelos scripts de setup/deploy do Modal."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_LOCAL = ROOT / ".env.local"
ENV_EXAMPLE = ROOT / ".env.example"

API_APP = os.environ.get("RAG_API_APP", "backstage-rag-api")
LLM_APP = os.environ.get("RAG_LLM_APP", "backstage-rag-llm")
SECRET = os.environ.get("RAG_MODAL_SECRET", "backstage-rag-keys")
VOLUME = os.environ.get("RAG_MODAL_VOLUME", "backstage-rag-data")
MIN_MODAL = (1, 6, 2)


def modal_cmd() -> list[str]:
    exe = shutil.which("modal")
    return [exe] if exe else [sys.executable, "-m", "modal"]


def run(args: list[str], *, check: bool = True, capture: bool = False, show: bool = True) -> subprocess.CompletedProcess:
    cmd = modal_cmd() + args
    if show:
        print(">", "modal", " ".join(args), flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=capture,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def ensure_modal_login() -> None:
    try:
        import modal
    except ImportError:
        sys.exit('O cliente do Modal não está instalado. Rode:  pip install -U "modal>=1.6.2"')
    version = tuple(int(x) for x in modal.__version__.split(".")[:3] if x.isdigit())
    if version < MIN_MODAL:
        # Testado: deploy feito com o cliente 1.6.1 sobe containers que quebram ao iniciar
        # (ImportError dentro do runtime do Modal). Atualize antes de qualquer deploy.
        sys.exit(f'Seu cliente do Modal é {modal.__version__}; precisa de >= 1.6.2. Rode:  pip install -U "modal>=1.6.2"')
    res = run(["token", "info"], check=False, capture=True, show=False)
    if res.returncode != 0:
        res = run(["profile", "current"], check=False, capture=True, show=False)
    if res.returncode != 0:
        sys.exit("Você ainda não fez login no Modal. Rode:  modal setup")


def secret_exists(name: str) -> bool:
    res = run(["secret", "list", "--json"], capture=True, show=False)
    return any(s.get("name") == name for s in json.loads(res.stdout or "[]"))


# ------------------------------------------------------------------ .env.local
def read_env(path: Path = ENV_LOCAL) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def update_env(updates: dict[str, str], path: Path = ENV_LOCAL) -> None:
    """Atualiza só as chaves pedidas e mantém o resto do arquivo como está."""
    if not path.is_file():
        path.write_text(ENV_EXAMPLE.read_text(encoding="utf-8") if ENV_EXAMPLE.is_file() else "", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    pending = dict(updates)
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in pending:
                lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
