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


def _csv_tuple(env_value: str | None, default) -> tuple[str, ...]:
    """Lista separada por vírgula (env tem prioridade; string vazia = nenhum)."""
    raw = env_value if env_value is not None else default
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = str(raw or "").split(",")
    return tuple(x.strip().lower() for x in items if str(x).strip())


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
    llm_timeout_s: float = 120.0  # LLM_TIMEOUT_S; no Modal é 300 pra esperar a partida a frio do vLLM
    # Ajudas de precisão da triagem (rag/triage_aids.py); a requisição pode sobrescrever no config
    triage_neighbor_labels: bool = True       # TRIAGE_NEIGHBOR_LABELS
    triage_label_descriptions: bool = True    # TRIAGE_LABEL_DESCRIPTIONS
    triage_neighbor_k: int = 5                # TRIAGE_NEIGHBOR_K
    triage_neighbor_cutoff: str = "2026-04-22T00:00:00Z"  # TRIAGE_NEIGHBOR_CUTOFF ("" desliga o filtro de data)
    # Reescrita da consulta (rag/query_rewrite.py) e votação de labels (rag/label_votes.py); desligadas por padrão
    query_rewrite: bool = False               # QUERY_REWRITE
    query_rewrite_mode: str = "fuse"          # QUERY_REWRITE_MODE: fuse | replace
    query_rewrite_weight: float = 0.5         # QUERY_REWRITE_WEIGHT: peso da reescrita no RRF (modo fuse)
    query_rewrite_lists: str = "dense"        # QUERY_REWRITE_LISTS: dense | bm25 | both (onde a reescrita entra)
    triage_label_votes: int = 1               # TRIAGE_LABEL_VOTES: 1 = desligado, 3 = 3 amostras e maioria
    triage_vote_temperature: float = 0.7      # TRIAGE_VOTE_TEMPERATURE
    # Busca 2 (18/10): todos desligados por padrão; a requisição pode ligar (config.*)
    split_types: bool = False                 # RETRIEVAL_SPLIT_TYPES: top-k separado issues/PRs x docs/ADRs (todos os índices)
    split_types_indices: tuple[str, ...] = ("logico",)  # RETRIEVAL_SPLIT_TYPES_INDICES: índices com split por padrão
    split_k_issues: int = 6                   # RETRIEVAL_SPLIT_K_ISSUES
    split_k_docs: int = 4                     # RETRIEVAL_SPLIT_K_DOCS
    bm25_title_boost: int = 0                 # BM25_TITLE_BOOST: repetições extras do título (0 = não monta o índice reforçado)
    bm25_label_boost: int = 0                 # BM25_LABEL_BOOST: repetições extras das labels
    bm25_boost: bool = False                  # BM25_BOOST: usar o índice reforçado por padrão (se montado)
    related_min_score: float | None = None    # RELATED_MIN_SCORE: corta related com score abaixo disto (vazio = desligado)
    related_score_kind: str = "dense"         # RELATED_SCORE_KIND: dense (cosseno) | rrf_rel (score/melhor score)
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

    # Busca híbrida: RRF_K, RRF_W_BM25 (peso do BM25; o denso fica com 1 - w) e RETRIEVAL_GROUP_BY_DOC.
    # Padrões escolhidos na varredura offline de 17/10 (ver testes/bateria_busca.xlsx).
    # Melhor combinação na varredura (base e logico, 82 issues): w_bm25=0.8, k=30, 1 chunk por doc.
    # O retrieval.rrf_k do config.yaml é do pipeline offline (query_demo/08_retrieve_eval); a API usa estes.
    rrf_k_env: int | None = None
    rrf_w_bm25: float = 0.8
    group_by_doc: bool = False
    chunks_per_doc: int = 3

    @property
    def rrf_k(self) -> int:
        if self.rrf_k_env is not None:
            return int(self.rrf_k_env)
        return int(self.cfg("retrieval", "api_rrf_k", default=30))

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


def _cfg_get(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    node: Any = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


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
        llm_timeout_s=_env_float("LLM_TIMEOUT_S") or 120.0,
        rag_api_key=os.getenv("RAG_API_KEY", ""),
        embed_device=os.getenv("EMBED_DEVICE", "cuda"),
        enable_reranker=_env_bool("ENABLE_RERANKER", True),
        cors_origins=origins,
        labels_path=Path(labels_env) if labels_env else None,
        log_path=Path(os.getenv("LOG_DIR", "logs")) / "requests.jsonl",
        prompts_dir=Path(os.getenv("PROMPTS_DIR", str(BACKEND_DIR / "prompts"))),
        triage_neighbor_labels=_env_bool("TRIAGE_NEIGHBOR_LABELS", bool(_cfg_get(config, "triage", "neighbor_labels", default=True))),
        triage_label_descriptions=_env_bool(
            "TRIAGE_LABEL_DESCRIPTIONS", bool(_cfg_get(config, "triage", "label_descriptions", default=True))
        ),
        triage_neighbor_k=int(os.getenv("TRIAGE_NEIGHBOR_K") or _cfg_get(config, "triage", "neighbor_k", default=5)),
        triage_neighbor_cutoff=os.getenv(
            "TRIAGE_NEIGHBOR_CUTOFF", str(_cfg_get(config, "triage", "neighbor_cutoff", default=config.get("cutoff") or "2026-04-22T00:00:00Z"))
        ),
        query_rewrite=_env_bool("QUERY_REWRITE", bool(_cfg_get(config, "triage", "query_rewrite", default=False))),
        query_rewrite_mode=(os.getenv("QUERY_REWRITE_MODE") or str(_cfg_get(config, "triage", "query_rewrite_mode", default="fuse"))).strip().lower(),
        query_rewrite_weight=_env_float("QUERY_REWRITE_WEIGHT") if _env_float("QUERY_REWRITE_WEIGHT") is not None else float(
            _cfg_get(config, "triage", "query_rewrite_weight", default=0.5)
        ),
        query_rewrite_lists=(os.getenv("QUERY_REWRITE_LISTS") or str(_cfg_get(config, "triage", "query_rewrite_lists", default="dense"))).strip().lower(),
        triage_label_votes=max(1, int(os.getenv("TRIAGE_LABEL_VOTES") or _cfg_get(config, "triage", "label_votes", default=1))),
        triage_vote_temperature=_env_float("TRIAGE_VOTE_TEMPERATURE") if _env_float("TRIAGE_VOTE_TEMPERATURE") is not None else float(
            _cfg_get(config, "triage", "vote_temperature", default=0.7)
        ),
        split_types=_env_bool("RETRIEVAL_SPLIT_TYPES", bool(_cfg_get(config, "retrieval", "split_types", default=False))),
        split_types_indices=_csv_tuple(
            os.getenv("RETRIEVAL_SPLIT_TYPES_INDICES"), _cfg_get(config, "retrieval", "split_types_indices", default="logico")
        ),
        split_k_issues=int(os.getenv("RETRIEVAL_SPLIT_K_ISSUES") or _cfg_get(config, "retrieval", "split_k_issues", default=6)),
        split_k_docs=int(os.getenv("RETRIEVAL_SPLIT_K_DOCS") or _cfg_get(config, "retrieval", "split_k_docs", default=4)),
        bm25_title_boost=int(os.getenv("BM25_TITLE_BOOST") or _cfg_get(config, "retrieval", "bm25_title_boost", default=0)),
        bm25_label_boost=int(os.getenv("BM25_LABEL_BOOST") or _cfg_get(config, "retrieval", "bm25_label_boost", default=0)),
        bm25_boost=_env_bool("BM25_BOOST", bool(_cfg_get(config, "retrieval", "bm25_boost", default=False))),
        related_min_score=_env_float("RELATED_MIN_SCORE") if _env_float("RELATED_MIN_SCORE") is not None else _cfg_get(
            config, "triage", "related_min_score", default=None
        ),
        related_score_kind=(os.getenv("RELATED_SCORE_KIND") or str(_cfg_get(config, "triage", "related_score_kind", default="dense"))).strip().lower(),
        rrf_k_env=int(os.environ["RRF_K"]) if os.getenv("RRF_K", "").strip() else None,
        rrf_w_bm25=_env_float("RRF_W_BM25") if _env_float("RRF_W_BM25") is not None else float(
            _cfg_get(config, "retrieval", "rrf_w_bm25", default=0.8)
        ),
        group_by_doc=_env_bool("RETRIEVAL_GROUP_BY_DOC", bool(_cfg_get(config, "retrieval", "group_by_doc", default=False))),
        chunks_per_doc=max(1, int(os.environ.get("RETRIEVAL_CHUNKS_PER_DOC") or _cfg_get(config, "retrieval", "chunks_per_doc", default=3))),
        config=config,
        min_score=_min_scores(config),
    )
