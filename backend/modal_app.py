"""API do Backstage RAG (FastAPI) no Modal, com GPU para o BGE-M3 e o reranker.

    python scripts/setup_modal.py     (1x por conta: Volume com os índices, secret, pesos do LLM)
    python scripts/deploy_modal.py    (deploy do LLM + desta API; grava a URL no .env.local)

    modal deploy backend/modal_app.py                   (só este app)
    modal run backend/modal_app.py::populate_volume     (baixa os índices do Google Drive para o Volume)

URL: https://<seu-workspace>--<RAG_API_APP>-fastapi-app.modal.run   (/health, /chat, /triage, /compare, /labels)

Variáveis lidas NA HORA DO DEPLOY (os valores vão para a imagem, o container vê os mesmos):
    RAG_API_APP        nome do app                          (padrão backstage-rag-api)
    RAG_LLM_APP        app do vLLM (modal/llm_qwen.py)      (padrão backstage-rag-llm)
    RAG_MODAL_VOLUME   Volume com a pasta data_full         (padrão backstage-rag-data)
    RAG_MODAL_SECRET   secret com RAG_API_KEY e LLM_API_KEY (padrão backstage-rag-keys)
    API_GPU            GPU do BGE-M3 + reranker             (padrão L4; T4 também serve)
    LLM_MODEL_ID       modelo servido pelo vLLM             (padrão Qwen/Qwen3.5-9B)
    MIN_SCORE_DENSE / MIN_SCORE_RERANK / MIN_SCORE_BM25   limiares do gate (padrão 0.55 / -1.0 / vazio)
    LLM_BASE_URL       vazio = descobre a URL do app RAG_LLM_APP na MESMA conta do Modal.
                       Para usar outro servidor (Ollama exposto, RunPod...), coloque a URL .../v1.

- Dados: Volume montado em /data, com a mesma estrutura de data_full (index/, index_lean/,
  index_logico/, chunks/, addons/). Os BM25 do enxuto e do base_extras são gerados pelo
  populate_volume com o mesmo tokenizer do 05b_bm25_index.py.
- Modelos: BAAI/bge-m3 e BAAI/bge-reranker-v2-m3 vão para dentro da imagem no build
  (HF_HUB_OFFLINE=1 em execução): o cold start não baixa nada.
- Custo: min_containers=0 e scaledown de 5 min. No dia da apresentação, min_containers=1 evita o
  cold start (mas cobra a GPU parada).
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
HF_CACHE = "/root/hf-cache"
DATA = "/data"

APP_NAME = os.environ.get("RAG_API_APP", "backstage-rag-api")
LLM_APP = os.environ.get("RAG_LLM_APP", "backstage-rag-llm")
VOLUME_NAME = os.environ.get("RAG_MODAL_VOLUME", "backstage-rag-data")
SECRET_NAME = os.environ.get("RAG_MODAL_SECRET", "backstage-rag-keys")
API_GPU = os.environ.get("API_GPU", "L4")
LLM_MODEL = os.environ.get("LLM_MODEL_ID", "Qwen/Qwen3.5-9B")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
# Limiares provisórios do gate (ver backend/.env.example); recalibrar com logs/requests.jsonl
MIN_SCORE_DENSE = os.environ.get("MIN_SCORE_DENSE", "0.55")
MIN_SCORE_RERANK = os.environ.get("MIN_SCORE_RERANK", "-1.0")
MIN_SCORE_BM25 = os.environ.get("MIN_SCORE_BM25", "")

# Pastas públicas do Google Drive com os índices (partes .tar.gz/.zip; ver LEIAME.txt de cada uma)
DRIVE_BUNDLES = {
    "base": {"folder": "1aEjtQUBayctUoK6z96nokYLDjid07Cdt", "check": "index/embeddings.npy"},
    "enxuto": {"folder": "1e2NJ0hzTCypEBxvuK51R-nYKTS9BAsYk", "check": "index_lean/embeddings.npy"},
    "logico": {"folder": "1uA90RfGYjslI7cVUT65k8elDlCleqJ8S", "check": "index_logico/embeddings.npy"},
    "base_extras": {"folder": "1BF6Dx9DlajgMUNzg8yebGZme1AYnOhij", "check": "addons/commit/embeddings.npy"},
}


def _download_models() -> None:
    """Roda no build da imagem: pesos do BGE-M3 e do reranker ficam dentro dela."""
    from huggingface_hub import snapshot_download

    snapshot_download("BAAI/bge-m3", allow_patterns=[
        "*.json", "*.txt", "sentencepiece.bpe.model", "pytorch_model.bin", "1_Pooling/*", "modules.json"])
    snapshot_download("BAAI/bge-reranker-v2-m3", allow_patterns=[
        "*.json", "*.txt", "sentencepiece.bpe.model", "model.safetensors"])


volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .pip_install("gdown==6.4.2")
    .env({"HF_HOME": HF_CACHE, "TOKENIZERS_PARALLELISM": "false"})
    .run_function(_download_models)
    .env(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "RAG_DATA_DIR": DATA,              # pasta data_full no Volume (índices base/enxuto/logico + addons)
            "DATA_DIR": DATA,
            "RAG_CONFIG": "/root/backend/config.yaml",
            "LABELS_PATH": "/root/data/labels.json",
            "EMBED_DEVICE": "cuda",
            "ENABLE_RERANKER": "true",
            "LOG_DIR": f"{DATA}/logs",          # logs de requisições no Volume (para calibrar MIN_SCORE)
            "RAG_LLM_APP": LLM_APP,
            "LLM_BASE_URL": LLM_BASE_URL,
            "LLM_MODEL": LLM_MODEL,
            "LLM_ENABLE_THINKING": "false",
            "LLM_TIMEOUT_S": "300",             # o 1º pedido pode esperar o cold start do vLLM
            "CORS_ORIGINS": "http://localhost:3000",
            "MIN_SCORE_DENSE": MIN_SCORE_DENSE,
            "MIN_SCORE_RERANK": MIN_SCORE_RERANK,
            "MIN_SCORE_BM25": MIN_SCORE_BM25,
            # Ajudas de precisão da triagem (rag/triage_aids.py); cada requisição pode sobrescrever no config
            "TRIAGE_NEIGHBOR_LABELS": os.environ.get("TRIAGE_NEIGHBOR_LABELS", "true"),
            "TRIAGE_LABEL_DESCRIPTIONS": os.environ.get("TRIAGE_LABEL_DESCRIPTIONS", "true"),
            "TRIAGE_NEIGHBOR_CUTOFF": os.environ.get("TRIAGE_NEIGHBOR_CUTOFF", "2026-04-22T00:00:00Z"),
            # Busca híbrida (varredura + confirmação de 17/10): RRF ponderado w_bm25=0.8, k=30, sem agrupar por doc.
            # Agrupar (RETRIEVAL_GROUP_BY_DOC=true, + RETRIEVAL_CHUNKS_PER_DOC) melhora o ranking mas não a triagem.
            "RRF_K": os.environ.get("RRF_K", "30"),
            "RRF_W_BM25": os.environ.get("RRF_W_BM25", "0.8"),
            "RETRIEVAL_GROUP_BY_DOC": os.environ.get("RETRIEVAL_GROUP_BY_DOC", "false"),
            "RETRIEVAL_CHUNKS_PER_DOC": os.environ.get("RETRIEVAL_CHUNKS_PER_DOC", "3"),
            # Reescrita da consulta e votação de labels (17/10): desligadas por padrão; a requisição pode ligar
            "QUERY_REWRITE": os.environ.get("QUERY_REWRITE", "false"),
            "QUERY_REWRITE_MODE": os.environ.get("QUERY_REWRITE_MODE", "fuse"),
            "QUERY_REWRITE_WEIGHT": os.environ.get("QUERY_REWRITE_WEIGHT", "0.5"),
            "QUERY_REWRITE_LISTS": os.environ.get("QUERY_REWRITE_LISTS", "dense"),
            "TRIAGE_LABEL_VOTES": os.environ.get("TRIAGE_LABEL_VOTES", "1"),
            "TRIAGE_VOTE_TEMPERATURE": os.environ.get("TRIAGE_VOTE_TEMPERATURE", "0.7"),
            # Busca 2 (18/10): desligados por padrão; a requisição pode ligar (split_types, bm25_boost, related_min_score)
            "RETRIEVAL_SPLIT_TYPES": os.environ.get("RETRIEVAL_SPLIT_TYPES", "false"),
            # 18/10: split 6+4 ligado por padrão só no índice lógico (a requisição ainda decide)
            "RETRIEVAL_SPLIT_TYPES_INDICES": os.environ.get("RETRIEVAL_SPLIT_TYPES_INDICES", "logico"),
            "RETRIEVAL_SPLIT_K_ISSUES": os.environ.get("RETRIEVAL_SPLIT_K_ISSUES", "6"),
            "RETRIEVAL_SPLIT_K_DOCS": os.environ.get("RETRIEVAL_SPLIT_K_DOCS", "4"),
            "BM25_TITLE_BOOST": os.environ.get("BM25_TITLE_BOOST", "0"),
            "BM25_LABEL_BOOST": os.environ.get("BM25_LABEL_BOOST", "0"),
            "BM25_BOOST": os.environ.get("BM25_BOOST", "false"),
            "RELATED_MIN_SCORE": os.environ.get("RELATED_MIN_SCORE", ""),
            "RELATED_SCORE_KIND": os.environ.get("RELATED_SCORE_KIND", "dense"),
        }
    )
    .add_local_file(str(PROJECT / "data" / "labels.json"), "/root/data/labels.json")
    .add_local_dir(str(HERE), remote_path="/root/backend",
                   ignore=[".venv", "tests", "logs", "**/__pycache__", ".env", ".pytest_cache", "data_full"])
)

app = modal.App(APP_NAME, image=image)


def _resolve_llm_url() -> None:
    """LLM_BASE_URL vazio: usa o app do vLLM da mesma conta (nada fixo no código)."""
    if os.environ.get("LLM_BASE_URL"):
        return
    try:
        url = modal.Function.from_name(os.environ["RAG_LLM_APP"], "serve").get_web_url()
        os.environ["LLM_BASE_URL"] = url.rstrip("/") + "/v1"
        print("LLM_BASE_URL =", os.environ["LLM_BASE_URL"], flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Não achei o app {os.environ.get('RAG_LLM_APP')!r} ({exc}); defina LLM_BASE_URL.", flush=True)


@app.function(
    gpu=API_GPU,
    memory=16384,
    volumes={DATA: volume},
    secrets=[modal.Secret.from_name(SECRET_NAME, required_keys=["RAG_API_KEY", "LLM_API_KEY"])],
    timeout=600,
    min_containers=0,
    scaledown_window=300,
)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def fastapi_app():
    import sys

    sys.path.insert(0, "/root/backend")
    _resolve_llm_url()
    from api import create_app

    return create_app()


# --------------------------------------------------------------------------- #
# Setup: popula o Volume com os índices (roda 1x por conta; sem GPU)
# --------------------------------------------------------------------------- #
def _extract(archive: Path, dest: Path) -> None:
    import tarfile
    import zipfile

    def target(name: str) -> Path | None:
        name = name.lstrip("./")
        if name.startswith("data_full/"):       # o pacote base-com-extras traz data_full/ na frente
            name = name[len("data_full/"):]
        if not name or ".." in Path(name).parts:
            return None
        return dest / name

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                out = target(info.filename)
                if out is None or info.is_dir():
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
        return
    with tarfile.open(archive, "r:*") as tf:
        for member in tf:
            out = target(member.name)
            if out is None or not member.isfile():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, open(out, "wb") as dst:  # type: ignore[union-attr]
                while chunk := src.read(1 << 20):
                    dst.write(chunk)


def _build_bm25(name: str, sources: list[Path], out: Path) -> None:
    """Mesmo processo do 05b_bm25_index.py (bm25s + stopwords en + Snowball english)."""
    import json
    import sys

    import bm25s

    sys.path.insert(0, "/root/backend")
    from rag.settings import load_settings
    from rag.text import BM25Tokenizer

    ids, texts = [], []
    for src in sources:
        with src.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    ids.append(row["id"])
                    texts.append(row["text"])
    tok = BM25Tokenizer(load_settings().bm25_config)
    model = bm25s.BM25()
    model.index(tok.corpus(texts), show_progress=False)
    out.mkdir(parents=True, exist_ok=True)
    model.save(str(out))
    (out / "bm25_ids.json").write_text(json.dumps(ids))
    print(f"BM25 {name}: {len(ids)} chunks -> {out}", flush=True)


@app.function(volumes={DATA: volume}, timeout=2 * 60 * 60, cpu=4, memory=16384)
def populate_volume(only: str = "", force: bool = False) -> dict[str, str]:
    """Baixa as partes do Google Drive (gdown), junta, extrai em /data e gera os BM25 que faltam."""
    import shutil
    import tempfile

    import gdown

    data = Path(DATA)
    wanted = [n.strip() for n in only.split(",") if n.strip()] or list(DRIVE_BUNDLES)
    status: dict[str, str] = {}
    for name in wanted:
        bundle = DRIVE_BUNDLES[name]
        if (data / bundle["check"]).is_file() and not force:
            status[name] = "já estava no Volume"
            print(f"[{name}] já existe ({bundle['check']}); pulando", flush=True)
            continue
        tmp = Path(tempfile.mkdtemp(dir="/tmp"))
        print(f"[{name}] baixando do Google Drive...", flush=True)
        gdown.download_folder(id=bundle["folder"], output=str(tmp), quiet=True)
        parts = sorted(p for p in tmp.rglob("*") if p.is_file() and ".part" in p.name)
        if not parts:
            raise RuntimeError(f"[{name}] nenhuma parte encontrada na pasta do Drive {bundle['folder']}")
        archive = tmp / parts[0].name.split(".part")[0]
        with archive.open("wb") as dst:
            for part in parts:
                with part.open("rb") as src:
                    shutil.copyfileobj(src, dst, 1 << 22)
                part.unlink()
        print(f"[{name}] extraindo {archive.name} ({archive.stat().st_size / 1e6:.0f} MB)...", flush=True)
        _extract(archive, data)
        shutil.rmtree(tmp, ignore_errors=True)
        volume.commit()
        status[name] = "baixado"

    if (data / "index_lean/chunks.jsonl").is_file() and (force or not (data / "index_lean/bm25/bm25_ids.json").is_file()):
        _build_bm25("enxuto", [data / "index_lean/chunks.jsonl"], data / "index_lean/bm25")
    extras_src = [data / "chunks/chunks.jsonl"] + [data / f"addons/{a}/chunks.jsonl" for a in ("changelog", "commit", "review")]
    if all(p.is_file() for p in extras_src) and (force or not (data / "addons/base_extras_bm25/bm25_ids.json").is_file()):
        _build_bm25("base_extras", extras_src, data / "addons/base_extras_bm25")
    volume.commit()
    print("Volume pronto:", status, flush=True)
    return status


@app.local_entrypoint()
def setup(only: str = "", force: bool = False) -> None:
    """modal run backend/modal_app.py::setup [--only base,logico] [--force]"""
    print(populate_volume.remote(only=only, force=force))
