"""Configuração: variáveis de ambiente (.env) + config.yaml do time."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("rag.settings")

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Gate de MIN_SCORE (seção 7 da spec). Não há valor fixo no código: os limiares vêm
# do config.yaml (guardrails.min_score.{dense,bm25,rerank}) ou do env
# (MIN_SCORE_DENSE, MIN_SCORE_BM25, MIN_SCORE_RERANK). Escalas diferentes:
#  - dense: 1 - distância cosseno (0..1)
#  - bm25: score bruto do BM25 (sem limite superior)
#  - rerank: LOGIT do bge-reranker-v2-m3 (sem sigmoid; pode ser negativo)
# Sem limiar configurado, o gate só recusa quando a busca não trouxe nada.
# Calibre com os top scores gravados em logs/requests.jsonl.
MIN_SCORE_KEYS = ("dense", "bm25", "rerank")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("Valor inválido em %s=%r; ignorando", name, raw)
        return None


@dataclass
class Settings:
    data_dir: Path = Path("data_full")
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"
    rag_api_key: str = ""
    embed_device: str = "cuda"
    enable_reranker: bool = True
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    labels_path: Path | None = None
    log_path: Path = Path("logs/requests.jsonl")
    prompts_dir: Path = BACKEND_DIR / "prompts"
    llm_timeout_s: float = 120.0
    config: dict[str, Any] = field(default_factory=dict)
    min_score: dict[str, float | None] = field(default_factory=dict)

    # --- atalhos para chaves do config.yaml ---
    def cfg(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.config
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def chroma_collection(self) -> str:
        return str(self.cfg("embed", "chroma_collection", default="backstage_chunks"))

    def collection_for(self, index: str) -> str:
        """Coleção Chroma de cada índice: base usa a do config; logico tem a sua."""
        if index == "logico":
            return str(self.cfg("embed", "chroma_collection_logico", default=f"{self.chroma_collection}_logico"))
        if index == "enxuto":
            return str(self.cfg("embed", "chroma_collection_enxuto", default=self.chroma_collection))
        return self.chroma_collection

    @property
    def embed_model(self) -> str:
        return str(self.cfg("embed", "model", default="BAAI/bge-m3"))

    @property
    def rerank_model(self) -> str:
        return str(self.cfg("rerank", "model", default="BAAI/bge-reranker-v2-m3"))

    @property
    def rrf_k(self) -> int:
        return int(self.cfg("retrieval", "rrf_k", default=60))

    @property
    def max_context_tokens(self) -> int:
        return int(self.cfg("retrieval", "max_context_tokens", default=6000))

    @property
    def bm25_config(self) -> dict[str, Any]:
        """Bloco de configuração do BM25 (aceita `bm25:` ou `retrieval.bm25:`)."""
        block = self.cfg("bm25") or self.cfg("retrieval", "bm25") or {}
        return block if isinstance(block, dict) else {}


def _find_config(data_dir: Path) -> Path | None:
    env_path = os.getenv("RAG_CONFIG")
    if env_path:
        return Path(env_path)
    for candidate in (data_dir.parent / "config.yaml", data_dir / "config.yaml", Path.cwd() / "config.yaml"):
        if candidate.is_file():
            return candidate
    return None


def load_yaml_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        log.warning("config.yaml não encontrado; usando padrões")
        return {}
    import yaml  # import tardio: só quando há arquivo

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _min_scores(config: dict[str, Any]) -> dict[str, float | None]:
    """Env tem prioridade sobre o config.yaml."""
    guard = config.get("guardrails") if isinstance(config.get("guardrails"), dict) else {}
    from_cfg = guard.get("min_score") if isinstance(guard.get("min_score"), dict) else {}
    scores: dict[str, float | None] = {}
    for key in MIN_SCORE_KEYS:
        env_val = _env_float(f"MIN_SCORE_{key.upper()}")
        cfg_val = from_cfg.get(key)
        scores[key] = env_val if env_val is not None else (float(cfg_val) if cfg_val is not None else None)
    missing = [k for k, v in scores.items() if v is None]
    if missing:
        log.warning("MIN_SCORE sem valor para %s: o gate só recusa quando a busca vem vazia", ", ".join(missing))
    return scores


def default_data_dir() -> Path:
    """DATA_DIR; RAG_DATA_DIR ainda vale (modal_app.py usa). Padrão: /data no Modal, ./data_full local."""
    for name in ("DATA_DIR", "RAG_DATA_DIR"):
        value = os.getenv(name)
        if value:
            return Path(value)
    on_modal = bool(os.getenv("MODAL_TASK_ID") or os.getenv("MODAL_ENVIRONMENT"))
    return Path("/data") if on_modal else Path("data_full")


def load_settings() -> Settings:
    """Lê .env (cwd e backend/) e o config.yaml."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv(BACKEND_DIR / ".env")
    except ImportError:  # python-dotenv é opcional
        pass

    data_dir = default_data_dir()
    config = load_yaml_config(_find_config(data_dir))
    labels_env = os.getenv("LABELS_PATH")
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

    return Settings(
        data_dir=data_dir,
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "qwen2.5:7b"),
        rag_api_key=os.getenv("RAG_API_KEY", ""),
        embed_device=os.getenv("EMBED_DEVICE", "cuda"),
        enable_reranker=_env_bool("ENABLE_RERANKER", True),
        cors_origins=origins,
        labels_path=Path(labels_env) if labels_env else None,
        log_path=Path(os.getenv("LOG_DIR", "logs")) / "requests.jsonl",
        prompts_dir=Path(os.getenv("PROMPTS_DIR", str(BACKEND_DIR / "prompts"))),
        config=config,
        min_score=_min_scores(config),
    )
