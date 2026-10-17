"""Exemplo: servir a mesma API no Modal.

    modal deploy modal_app.py        (rodar dentro de backend/)

Antes, suba os dados para o Volume (uma vez):
    modal volume create backstage-rag-data
    modal volume put backstage-rag-data ../data_full /data_full
    modal volume put backstage-rag-data ../data/labels.json /labels.json
    modal volume put backstage-rag-data ../config.yaml /config.yaml

E crie o secret com as variáveis do .env (RAG_API_KEY, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, CORS_ORIGINS):
    modal secret create backstage-rag-env RAG_API_KEY=... LLM_BASE_URL=... ...
"""
from __future__ import annotations

import modal

volume = modal.Volume.from_name("backstage-rag-data", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .env(
        {
            "RAG_DATA_DIR": "/data/data_full",
            "RAG_CONFIG": "/data/config.yaml",
            "LABELS_PATH": "/data/labels.json",
            "EMBED_DEVICE": "cuda",
            "LOG_DIR": "/data/logs",           # logs ficam no Volume
            "HF_HOME": "/data/hf-cache",       # pesos do BGE-M3/reranker baixam uma vez só
        }
    )
    .add_local_dir(".", remote_path="/root/backend", ignore=[".venv", "tests", "logs", "__pycache__"])
)

app = modal.App("backstage-rag-api", image=image)


@app.function(
    gpu="T4",
    volumes={"/data": volume},
    secrets=[modal.Secret.from_name("backstage-rag-env")],
    timeout=600,
    # min_containers=1 evita cold start (carregar BGE-M3 + índices leva ~1 min), mas cobra GPU parada.
    # Deixe 0 em desenvolvimento e 1 no dia da apresentação.
    min_containers=0,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def fastapi_app():
    import sys

    sys.path.insert(0, "/root/backend")
    from api import create_app

    return create_app()
