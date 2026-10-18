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
CANDIDATES_SPLIT = 150   # com RETRIEVAL_SPLIT_TYPES: mais candidatos, para sobrar doc/ADR suficiente
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
        number = int(value) if isinstance(value, int) or str(value).isdigit() else None
        # docs/ADRs vêm com number=-1 (ou vazio): sem número, a citação usa o doc_id
        return number if number is not None and number > 0 else None

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
def rrf_fuse(
    rankings: list[list[tuple[str, float]]], k: int = 60, weights: list[float] | None = None
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion ponderado: score = Σ w_i/(k + rank_i), rank começando em 1.

    Sem `weights`, todos os pesos valem 1 (RRF clássico)."""
    scores: dict[str, float] = defaultdict(float)
    for i, ranking in enumerate(rankings):
        w = 1.0 if weights is None else float(weights[i])
        if w == 0:
            continue
        for rank, (doc_id, _) in enumerate(ranking, start=1):
            scores[doc_id] += w / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _fuse_same_kind(lists: list[list[tuple[str, float]]], weights: list[float], k: int) -> list[tuple[str, float]]:
    """Junta listas do mesmo tipo (várias consultas) numa só, para os modos só-denso/só-BM25.
    Com uma lista só, devolve ela mesma (scores originais)."""
    if not lists:
        return []
    if len(lists) == 1:
        return lists[0]
    return rrf_fuse(lists, k, weights=weights)


def default_split_types(settings, index_name: str | None) -> bool:
    """Split issues/docs por padrão: RETRIEVAL_SPLIT_TYPES liga em todos os índices;
    RETRIEVAL_SPLIT_TYPES_INDICES (padrão "logico") liga só nos índices listados.
    config.split_types da requisição sempre tem prioridade (ver _pick)."""
    if getattr(settings, "split_types", False):
        return True
    names = getattr(settings, "split_types_indices", ()) or ()
    return (index_name or "").strip().lower() in {n.strip().lower() for n in names}


def _pick(request_value: Any, default: Any) -> Any:
    """Valor da requisição (config) quando informado; senão o padrão do servidor."""
    return default if request_value is None else request_value


def split_by_type(
    candidates: list[Hit],
    top_k: int,
    k_issues: int,
    k_docs: int,
    is_reasonable: Callable[[int, Hit], bool],
    max_per_doc: int = MAX_PER_DOC,
) -> list[Hit]:
    """Top-k separado por tipo: até k_issues de issues/PRs e k_docs de docs/ADRs (proporcional
    quando top_k != k_issues + k_docs). Se um lado não tiver candidatos suficientes, o outro
    completa. A ordem final segue o ranking original."""
    total = max(1, k_issues + k_docs)
    ki = min(top_k, round(top_k * k_issues / total))
    kd = top_k - ki
    issues = [h for h in candidates if type_group(h) != "doc_adr"]
    docs = [h for h in candidates if type_group(h) == "doc_adr"]
    sel_i = diversify(issues, ki, is_reasonable, max_per_doc=max_per_doc)
    sel_d = diversify(docs, kd, is_reasonable, max_per_doc=max_per_doc)
    if len(sel_i) < ki:
        sel_d = diversify(docs, top_k - len(sel_i), is_reasonable, max_per_doc=max_per_doc)
    elif len(sel_d) < kd:
        sel_i = diversify(issues, top_k - len(sel_d), is_reasonable, max_per_doc=max_per_doc)
    rank = {id(h): r for r, h in enumerate(candidates)}
    return sorted(sel_i + sel_d, key=lambda h: rank[id(h)])


def group_by_doc(hits: list[Hit]) -> list[Hit]:
    """Fica só com o melhor chunk de cada doc_id (a lista já vem ordenada), antes do top_k.

    Assim o top_k conta documentos (issues/PRs/docs/ADRs) e não chunks repetidos do mesmo doc."""
    seen: set[str] = set()
    out: list[Hit] = []
    for hit in hits:
        if hit.doc_id in seen:
            continue
        seen.add(hit.doc_id)
        out.append(hit)
    return out


def attach_doc_chunks(
    docs: list[Hit], candidates: list[Hit], chunks_per_doc: int, max_tokens: int | None = None
) -> list[Hit]:
    """Opção (d): os docs já foram escolhidos (1 chunk por doc); agora anexa até `chunks_per_doc`
    chunks de cada doc, pegando os mais bem ranqueados entre os candidatos.

    Os extras entram em rodadas (2º chunk de cada doc, na ordem dos docs; depois o 3º...) e só
    enquanto couberem em `max_tokens`, para que nenhum doc escolhido saia do contexto por causa do
    teto. Os extras herdam o score do doc, então o trecho final mantém a ordem dos docs."""
    if chunks_per_doc <= 1 or not docs:
        return list(docs)
    chosen = {h.doc_id: h for h in docs}
    extras: dict[str, list[Hit]] = defaultdict(list)
    head_ids = {h.id for h in docs}
    for hit in candidates:
        if hit.doc_id in chosen and hit.id not in head_ids and len(extras[hit.doc_id]) < chunks_per_doc - 1:
            extras[hit.doc_id].append(replace(hit, score=chosen[hit.doc_id].score))
    budget = None if max_tokens is None else max_tokens - sum(approx_tokens(h.text) for h in docs)
    out = list(docs)
    for rnd in range(chunks_per_doc - 1):
        for head in docs:
            more = extras.get(head.doc_id, [])
            if rnd >= len(more):
                continue
            cost = approx_tokens(more[rnd].text)
            if budget is not None:
                if cost > budget:
                    continue
                budget -= cost
            out.append(more[rnd])
    return out


def order_by_doc(passages: list[Hit], docs: list[Hit]) -> list[Hit]:
    """Reordena os trechos pela ordem em que os docs foram escolhidos (estável)."""
    rank = {h.doc_id: i for i, h in enumerate(docs)}
    return sorted(passages, key=lambda h: rank.get(h.doc_id, len(rank)))


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

    def _embed_many(self, queries: list[str]) -> list[Any]:
        with self._model_lock:
            return list(self.embedder.encode(queries))

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

    def retrieve(
        self,
        query: str,
        config: "RagConfig",
        top_k: int,
        alt_query: str | None = None,
        alt_mode: str = "fuse",
        alt_weight: float = 1.0,
        alt_lists: str = "both",
    ) -> RetrievalResult:
        """`alt_query` = consulta reescrita pelo LLM (QUERY_REWRITE). alt_mode "fuse": as listas da
        original e da reescrita entram juntas no RRF, a reescrita com peso `alt_weight` e só nas buscas
        de `alt_lists` ("dense", "bm25" ou "both"); "replace": só a reescrita é usada."""
        index = self.indices.get(config.index)
        if index is None:
            raise RetrievalError(f"Índice '{config.index}' não está disponível. Disponíveis: {self.available_indices}")
        if config.search in ("bm25", "hybrid") and index.bm25 is None:
            raise RetrievalError(f"O índice '{config.index}' não tem BM25 carregado.")

        t0 = time.perf_counter()
        st = self.settings
        split = _pick(getattr(config, "split_types", None), default_split_types(st, config.index))
        use_boost = _pick(getattr(config, "bm25_boost", None), getattr(st, "bm25_boost", False))
        bm25 = getattr(index, "bm25_boost", None) if use_boost else None
        bm25 = bm25 or index.bm25  # BM25_TITLE_BOOST/BM25_LABEL_BOOST: índice com título/labels reforçados
        n_search = CANDIDATES_SPLIT if split else CANDIDATES
        alt = (alt_query or "").strip()
        dense_q: list[tuple[str, float]] = [(query, 1.0)]
        sparse_q: list[tuple[str, float]] = [(query, 1.0)]
        if alt and alt_mode == "replace":
            dense_q = sparse_q = [(alt, 1.0)]
        elif alt and alt != query.strip():
            if alt_lists in ("dense", "both"):
                dense_q = dense_q + [(alt, float(alt_weight))]
            if alt_lists in ("bm25", "both"):
                sparse_q = sparse_q + [(alt, float(alt_weight))]
        dense_lists: list[list[tuple[str, float]]] = []
        sparse_lists: list[list[tuple[str, float]]] = []
        if config.search in ("dense", "hybrid"):
            vecs = self._embed_many([q for q, _ in dense_q])
            dense_lists = [index.dense.search(v, n_search) for v in vecs]
        if config.search in ("bm25", "hybrid"):
            sparse_lists = [
                [(i, s) for i, s in bm25.search(q, n_search) if s > 0]  # type: ignore[union-attr]
                for q, _ in sparse_q
            ]
        dense = _fuse_same_kind(dense_lists, [w for _, w in dense_q], self.settings.rrf_k)
        sparse = _fuse_same_kind(sparse_lists, [w for _, w in sparse_q], self.settings.rrf_k)

        dense_scores: dict[str, float] = {}
        for lst in dense_lists:  # melhor cosseno de cada chunk entre as consultas (gate e dense_score)
            for cid, sc in lst:
                if sc > dense_scores.get(cid, float("-inf")):
                    dense_scores[cid] = sc
        top_scores: dict[str, float] = {}
        if dense_scores:
            top_scores["dense"] = round(max(dense_scores.values()), 4)
        if any(sparse_lists):
            top_scores["bm25"] = round(max(s for lst in sparse_lists for _, s in lst), 4)

        # Ordem: busca (dense/bm25 ou híbrida com RRF) -> reranker -> diversidade por fonte -> top_k
        if config.search == "dense":
            ranking, scorer = dense, "dense"
        elif config.search == "bm25":
            ranking, scorer = sparse, "bm25"
        else:
            w_bm25 = float(getattr(self.settings, "rrf_w_bm25", 0.8))
            # Uma lista por (consulta, tipo) no mesmo RRF: com 1 consulta é o RRF ponderado de antes
            lists = dense_lists + sparse_lists
            wts = [(1.0 - w_bm25) * w for _, w in dense_q][: len(dense_lists)] + [w_bm25 * w for _, w in sparse_q][: len(sparse_lists)]
            ranking = rrf_fuse(lists, self.settings.rrf_k, weights=wts)
            scorer = "dense"
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
            for cid, score in ranking[:n_search]
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

        if split:
            # RETRIEVAL_SPLIT_TYPES: top-k separado de issues/PRs e de docs/ADRs (ex.: 5 + 5)
            selected = split_by_type(
                candidates, top_k, int(getattr(st, "split_k_issues", 5)), int(getattr(st, "split_k_docs", 5)),
                self._is_reasonable(scorer), max_per_doc=1 if getattr(st, "group_by_doc", False) else MAX_PER_DOC,
            )
            merged = merge_neighbors(selected)
        elif getattr(self.settings, "group_by_doc", True):
            # RETRIEVAL_GROUP_BY_DOC: 1 chunk (o melhor) por documento antes do top_k
            docs = diversify(group_by_doc(candidates), top_k, self._is_reasonable(scorer), max_per_doc=1)
            # RETRIEVAL_CHUNKS_PER_DOC: depois de escolher os docs, anexa até N chunks de cada um
            per_doc = int(getattr(self.settings, "chunks_per_doc", 1) or 1)
            selected = attach_doc_chunks(docs, candidates, per_doc, self.settings.max_context_tokens)
            merged = order_by_doc(merge_neighbors(selected), docs)
        else:
            selected = diversify(candidates, top_k, self._is_reasonable(scorer))
            merged = merge_neighbors(selected)
        passages = cap_context(merged, self.settings.max_context_tokens)
        return RetrievalResult(
            hits=passages,
            scorer=scorer,
            relevance=relevance,
            timings_ms=timings,
            candidates=[(h.id, round(h.score, 4)) for h in candidates[:CANDIDATES]],
            top_scores=top_scores,
        )
