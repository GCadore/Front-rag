"""Retrieval (seção 5 da spec): dense, BM25, híbrido RRF, reranker, diversidade e montagem do contexto."""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Protocol

from .text import approx_tokens

if TYPE_CHECKING:
    from .indices import Index
    from .schemas import RagConfig
    from .settings import Settings

log = logging.getLogger("rag.retrieval")

CANDIDATES = 50          # top N de cada busca (e do reranker)
MAX_PER_DOC = 3          # diversidade: no máximo 3 chunks por doc_id
REASONABLE_RANK = 20     # para scores sem escala absoluta (bm25/rrf/rerank)
SNIPPET_CHARS = 300

TYPE_GROUPS = {"issue": "issue_pr", "pr": "issue_pr", "comment": "issue_pr", "doc": "doc_adr", "adr": "doc_adr"}


class RetrievalError(Exception):
    """Erro de uso (índice ou modo de busca indisponível) -> HTTP 400."""


@dataclass
class Hit:
    id: str
    doc_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    dense_score: float | None = None
    chunk_ids: list[str] = field(default_factory=list)

    @property
    def number(self) -> int | None:
        value = self.metadata.get("number")
        return int(value) if isinstance(value, int) or str(value).isdigit() else None

    @property
    def source_label(self) -> str:
        """De onde veio o trecho: "issue #119", "pr #600" ou o doc_id (docs/ADRs/extras)."""
        if self.metadata.get("source"):
            return str(self.metadata["source"])
        kind = str(self.metadata.get("type", ""))
        return f"{kind} #{self.number}" if kind and self.number is not None else self.doc_id

    def to_source(self, n: int) -> dict[str, Any]:
        """Formato de citação: [n] -> source, number, title, url (+ ids, snippet e score)."""
        return {
            "n": n,
            "id": self.id,
            "doc_id": self.doc_id,
            "source": self.source_label,
            "number": self.number,
            "type": str(self.metadata.get("type", "")),
            "title": str(self.metadata.get("title", "")),
            "url": str(self.metadata.get("url", "")),
            "snippet": make_snippet(self.text),
            "score": round(float(self.score), 4),
        }


@dataclass
class RetrievalResult:
    hits: list[Hit]
    scorer: str                   # "dense" | "bm25" | "rerank": define qual MIN_SCORE usar
    relevance: float              # melhor score na escala de `scorer` (para o gate)
    timings_ms: dict[str, int] = field(default_factory=dict)
    candidates: list[tuple[str, float]] = field(default_factory=list)  # para o log
    # Melhor score de cada etapa (dense, bm25, rrf, rerank), pra calibrar o MIN_SCORE.
    # O do reranker é logit, não probabilidade.
    top_scores: dict[str, float] = field(default_factory=dict)


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> Any: ...  # -> np.ndarray (n, dim), normalizado


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


def make_snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Primeiros ~300 caracteres, pulando o cabeçalho '[ISSUE #n] ...' do chunk."""
    body = text
    if text.startswith("[") and "\n\n" in text[:500]:
        body = text.split("\n\n", 1)[1]
    body = " ".join(body.split())
    return body if len(body) <= limit else body[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Funções puras (testáveis sem modelos)
# --------------------------------------------------------------------------- #
def rrf_fuse(rankings: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score = Σ 1/(k + rank), rank começando em 1."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (doc_id, _) in enumerate(ranking, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def type_group(hit: Hit) -> str | None:
    return TYPE_GROUPS.get(str(hit.metadata.get("type", "")))


def diversify(
    candidates: list[Hit],
    top_k: int,
    is_reasonable: Callable[[int, Hit], bool],
    max_per_doc: int = MAX_PER_DOC,
) -> list[Hit]:
    """No máximo `max_per_doc` chunks por doc_id e pelo menos 1 de cada grupo
    de tipo presente (issue/pr e doc/adr) quando houver candidato razoável."""
    per_doc: Counter[str] = Counter()
    selected: list[Hit] = []
    for hit in candidates:
        if len(selected) >= top_k:
            break
        if per_doc[hit.doc_id] < max_per_doc:
            selected.append(hit)
            per_doc[hit.doc_id] += 1

    rank_of = {id(h): r for r, h in enumerate(candidates)}
    for group in ("issue_pr", "doc_adr"):
        if any(type_group(h) == group for h in selected):
            continue
        best = next(
            (
                h
                for r, h in enumerate(candidates)
                if type_group(h) == group and is_reasonable(r, h) and per_doc[h.doc_id] < max_per_doc
            ),
            None,
        )
        if best is None:
            continue
        if len(selected) >= top_k:
            # troca o pior item de um grupo que tem mais de um representante
            counts = Counter(type_group(h) for h in selected)
            victim = next((h for h in reversed(selected) if counts[type_group(h)] > 1), None)
            if victim is None:
                continue
            selected.remove(victim)
            per_doc[victim.doc_id] -= 1
        selected.append(best)
        per_doc[best.doc_id] += 1
        selected.sort(key=lambda h: rank_of[id(h)])
    return selected


def merge_neighbors(hits: list[Hit]) -> list[Hit]:
    """Junta chunks vizinhos (chunk_index consecutivo) do mesmo doc_id num trecho só."""
    by_doc: dict[str, list[Hit]] = defaultdict(list)
    for hit in hits:
        by_doc[hit.doc_id].append(hit)

    passages: list[Hit] = []
    for doc_hits in by_doc.values():
        def idx(h: Hit) -> int | None:
            value = h.metadata.get("chunk_index")
            return int(value) if isinstance(value, (int, float)) or str(value).isdigit() else None

        ordered = sorted(doc_hits, key=lambda h: (idx(h) is None, idx(h) or 0))
        run: list[Hit] = []
        for hit in ordered:
            if run and idx(hit) is not None and idx(run[-1]) is not None and idx(hit) == idx(run[-1]) + 1:
                run.append(hit)
                continue
            if run:
                passages.append(_join_run(run))
            run = [hit]
        if run:
            passages.append(_join_run(run))
    return sorted(passages, key=lambda h: h.score, reverse=True)


def _join_run(run: list[Hit]) -> Hit:
    if len(run) == 1:
        h = run[0]
        return replace(h, chunk_ids=h.chunk_ids or [h.id])
    best = max(run, key=lambda h: h.score)
    dense = [h.dense_score for h in run if h.dense_score is not None]
    return Hit(
        id=run[0].id,
        doc_id=run[0].doc_id,
        text="\n".join(h.text for h in run),
        metadata=run[0].metadata,
        score=best.score,
        dense_score=max(dense) if dense else None,
        chunk_ids=[h.id for h in run],
    )


def cap_context(passages: list[Hit], max_tokens: int = 6000, min_tail_tokens: int = 100) -> list[Hit]:
    """Limita o contexto total a ~max_tokens (aprox. chars/4)."""
    out: list[Hit] = []
    budget = max_tokens
    for hit in passages:
        cost = approx_tokens(hit.text)
        if cost <= budget:
            out.append(hit)
            budget -= cost
            continue
        if budget >= min_tail_tokens:
            out.append(replace(hit, text=hit.text[: budget * 4].rstrip() + " [...]"))
        break
    return out


# --------------------------------------------------------------------------- #
# Retriever
# --------------------------------------------------------------------------- #
class Retriever:
    """Junta índices + modelos. Thread-safe para uso via asyncio.to_thread."""

    def __init__(
        self,
        settings: "Settings",
        indices: dict[str, "Index"],
        embedder: Embedder,
        reranker: Reranker | None = None,
    ):
        self.settings = settings
        self.indices = indices
        self.embedder = embedder
        self.reranker = reranker
        self._model_lock = threading.Lock()  # GPU: um encode/predict por vez

    @property
    def available_indices(self) -> list[str]:
        return list(self.indices)

    @property
    def has_reranker(self) -> bool:
        return self.reranker is not None

    def _embed(self, query: str) -> Any:
        with self._model_lock:
            return self.embedder.encode([query])[0]

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        assert self.reranker is not None
        with self._model_lock:
            scores = self.reranker.score(query, [h.text for h in hits])
        reranked = [replace(h, score=float(s)) for h, s in zip(hits, scores)]
        return sorted(reranked, key=lambda h: h.score, reverse=True)

    def _is_reasonable(self, scorer: str) -> Callable[[int, Hit], bool]:
        threshold = self.settings.min_score.get("dense")
        if scorer == "dense" and threshold is not None:
            return lambda rank, h: (h.dense_score if h.dense_score is not None else h.score) >= threshold
        return lambda rank, h: rank < REASONABLE_RANK

    def retrieve(self, query: str, config: "RagConfig", top_k: int) -> RetrievalResult:
        index = self.indices.get(config.index)
        if index is None:
            raise RetrievalError(f"Índice '{config.index}' não está disponível. Disponíveis: {self.available_indices}")
        if config.search in ("bm25", "hybrid") and index.bm25 is None:
            raise RetrievalError(f"O índice '{config.index}' não tem BM25 carregado.")

        t0 = time.perf_counter()
        dense: list[tuple[str, float]] = []
        sparse: list[tuple[str, float]] = []
        if config.search in ("dense", "hybrid"):
            dense = index.dense.search(self._embed(query), CANDIDATES)
        if config.search in ("bm25", "hybrid"):
            sparse = [(i, s) for i, s in index.bm25.search(query, CANDIDATES) if s > 0]  # type: ignore[union-attr]

        dense_scores = dict(dense)
        top_scores: dict[str, float] = {}
        if dense:
            top_scores["dense"] = round(max(s for _, s in dense), 4)
        if sparse:
            top_scores["bm25"] = round(max(s for _, s in sparse), 4)

        # Ordem: busca (dense/bm25 ou híbrida com RRF) -> reranker -> diversidade por fonte -> top_k
        if config.search == "dense":
            ranking, scorer = dense, "dense"
        elif config.search == "bm25":
            ranking, scorer = sparse, "bm25"
        else:
            ranking, scorer = rrf_fuse([dense, sparse], self.settings.rrf_k), "dense"
            if ranking:
                top_scores["rrf"] = round(ranking[0][1], 6)

        candidates = [
            Hit(
                id=cid,
                doc_id=str(index.chunk(cid).metadata.get("doc_id") or cid),
                text=index.chunk(cid).text,
                metadata=index.chunk(cid).metadata,
                score=float(score),
                dense_score=dense_scores.get(cid),
            )
            for cid, score in ranking[:CANDIDATES]
            if index.has_chunk(cid)
        ]
        # Gate: no híbrido usamos o melhor score denso (o RRF não tem escala absoluta)
        if scorer == "dense":
            relevance = max(dense_scores.values(), default=float("-inf"))
        else:
            relevance = candidates[0].score if candidates else float("-inf")
        timings = {"retrieval": int((time.perf_counter() - t0) * 1000)}

        if config.reranker and self.reranker is not None and candidates:
            t1 = time.perf_counter()
            candidates = self._rerank(query, candidates)
            scorer, relevance = "rerank", candidates[0].score
            top_scores["rerank"] = round(relevance, 4)
            timings["rerank"] = int((time.perf_counter() - t1) * 1000)

        selected = diversify(candidates, top_k, self._is_reasonable(scorer))
        passages = cap_context(merge_neighbors(selected), self.settings.max_context_tokens)
        return RetrievalResult(
            hits=passages,
            scorer=scorer,
            relevance=relevance,
            timings_ms=timings,
            candidates=[(h.id, round(h.score, 4)) for h in candidates[:CANDIDATES]],
            top_scores=top_scores,
        )
