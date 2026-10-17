"""Fluxos de /chat, /triage e /compare, independentes do FastAPI (fáceis de testar)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from . import guardrails as gr
from .llm import FRIENDLY_LLM_ERROR, LLM, LLMError
from .prompts import PromptStore, chat_messages, triage_correction, triage_messages
from .reqlog import RequestLogger
from .retrieval import RetrievalError, RetrievalResult
from .schemas import CompareRequest, Message, RagConfig
from .settings import Settings
from .text import clean_issue_body

DEFAULT_TOP_K = {"chat": 8, "triage": 10}


class RetrieverLike(Protocol):
    @property
    def available_indices(self) -> list[str]: ...

    @property
    def has_reranker(self) -> bool: ...

    def retrieve(self, query: str, config: RagConfig, top_k: int) -> RetrievalResult: ...


@dataclass
class Services:
    """Tudo que os endpoints usam; montado uma vez no lifespan (ou com fakes nos testes)."""

    settings: Settings
    retriever: RetrieverLike | None
    llm: LLM
    labels: list[dict[str, Any]]          # já filtradas para triagem
    prompts: PromptStore
    request_log: RequestLogger

    @property
    def allowed_labels(self) -> set[str]:
        return {str(lb["name"]) for lb in self.labels}

    @property
    def available_indices(self) -> list[str]:
        return self.retriever.available_indices if self.retriever else []


def llm_unavailable(**extra: Any) -> dict[str, Any]:
    """Corpo de erro quando o LLM está frio ou fora do ar (HTTP 503 / evento SSE `error`)."""
    return {"error": "llm_unavailable", "retry": True, "message": FRIENDLY_LLM_ERROR, **extra}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def effective_config(services: Services, cfg: RagConfig, mode: str) -> RagConfig:
    reranker_ok = bool(services.settings.enable_reranker and services.retriever and services.retriever.has_reranker)
    return cfg.model_copy(
        update={
            "top_k": cfg.top_k or DEFAULT_TOP_K[mode],
            "reranker": bool(cfg.rag and cfg.reranker and reranker_ok),
        }
    )


async def run_retrieval(services: Services, query: str, cfg: RagConfig) -> RetrievalResult:
    if services.retriever is None:
        raise ApiError(503, "Os índices do RAG não estão carregados nesta instância.")
    try:
        return await asyncio.to_thread(services.retriever.retrieve, query, cfg, cfg.top_k or 8)
    except RetrievalError as exc:
        raise ApiError(400, str(exc)) from exc


def _log(services: Services, endpoint: str, cfg: RagConfig, query: str, **fields: Any) -> None:
    retrieval: RetrievalResult | None = fields.pop("retrieval", None)
    record: dict[str, Any] = {
        "request_id": fields.pop("request_id", uuid.uuid4().hex),
        "endpoint": endpoint,
        "config": cfg.model_dump(),
        "query": query[:1000],
    }
    if retrieval is not None:
        record["retrieved"] = [
            {"id": h.id, "doc_id": h.doc_id, "chunk_ids": h.chunk_ids, "score": round(h.score, 4)} for h in retrieval.hits
        ]
        record["candidates"] = retrieval.candidates[:20]
        record["scorer"] = retrieval.scorer
        record["relevance"] = retrieval.relevance if retrieval.relevance != float("-inf") else None
        # Pra calibrar o MIN_SCORE: melhor score de cada etapa e o limiar usado (rerank = logit)
        record["top_scores"] = retrieval.top_scores
        record["min_score"] = {
            "scorer": retrieval.scorer,
            "threshold": services.settings.min_score.get(retrieval.scorer),
            "applied": cfg.guardrails,
        }
    record.update(fields)
    services.request_log.write(record)


# --------------------------------------------------------------------------- #
# /chat
# --------------------------------------------------------------------------- #
@dataclass
class ChatPlan:
    cfg: RagConfig
    question: str
    sources: list[dict[str, Any]]
    llm_messages: list[dict[str, str]] | None   # None = recusado pelo gate
    k: int                                       # nº de trechos válidos para citação
    retrieval: RetrievalResult | None
    started: float
    timings: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    mentions: gr.MentionGuard | None = None    # só com rag + guardrails

    @property
    def refused(self) -> bool:
        return self.llm_messages is None


def _split_conversation(messages: list[Message]) -> tuple[str, list[dict[str, str]]]:
    """Última mensagem do usuário = pergunta; as anteriores viram histórico."""
    last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=None)
    if last_user is None:
        raise ApiError(422, "Envie ao menos uma mensagem com role 'user'.")
    history = [
        {"role": m.role, "content": gr.cap_input(m.content)[0]}
        for m in messages[:last_user]
        if m.role in ("user", "assistant")
    ]
    return messages[last_user].content, history


async def plan_chat(services: Services, messages: list[Message], cfg: RagConfig) -> ChatPlan:
    started = time.perf_counter()
    cfg = effective_config(services, cfg, "chat")
    question, history = _split_conversation(messages)
    question, truncated = gr.cap_input(question)

    if not cfg.rag:  # modo "sem RAG" da comparação
        msgs = chat_messages(services.prompts, question, history, None, strict=False)
        return ChatPlan(cfg, question, [], msgs, 0, None, started, truncated=truncated)

    result = await run_retrieval(services, question, cfg)
    timings = {"retrieval": result.timings_ms.get("retrieval", 0), "rerank": result.timings_ms.get("rerank", 0)}
    if cfg.guardrails and not gr.passes_min_score(result, services.settings.min_score):
        return ChatPlan(cfg, question, [], None, 0, result, started, timings, truncated)

    sources = [h.to_source(n) for n, h in enumerate(result.hits, start=1)]
    msgs = chat_messages(services.prompts, question, history, result.hits, strict=cfg.guardrails)
    mentions = gr.MentionGuard(result.hits, [question] + [m["content"] for m in history]) if cfg.guardrails else None
    return ChatPlan(cfg, question, sources, msgs, len(result.hits), result, started, timings, truncated, mentions)


def _strip_enabled(plan: ChatPlan) -> bool:
    return plan.cfg.guardrails


async def chat_once(services: Services, messages: list[Message], cfg: RagConfig, endpoint: str = "chat") -> dict[str, Any]:
    plan = await plan_chat(services, messages, cfg)
    removed: list[int] = []
    removed_mentions: list[str] = []
    timings = dict(plan.timings)
    if plan.refused:
        answer = gr.REFUSAL_TEXT
    else:
        t_llm = time.perf_counter()
        try:
            answer = await services.llm.complete(plan.llm_messages or [], temperature=0.1)
        except LLMError as exc:
            _log(services, endpoint, plan.cfg, plan.question, retrieval=plan.retrieval, error=str(exc))
            raise
        timings["llm"] = _ms(t_llm)
        if _strip_enabled(plan):
            answer, removed = gr.strip_invalid_citations(answer, plan.k)
        if plan.mentions is not None:
            answer, removed_mentions = plan.mentions.apply(answer)
    timings["total"] = _ms(plan.started)

    _log(
        services, endpoint, plan.cfg, plan.question,
        retrieval=plan.retrieval, timings_ms=timings, refused=plan.refused,
        removed_citations=removed, removed_mentions=removed_mentions, input_truncated=plan.truncated,
    )
    return {
        "answer": answer,
        "sources": plan.sources,
        "rag": plan.cfg.rag,
        "config": plan.cfg.model_dump(),
        "timings_ms": timings,
        "refused": plan.refused,
        "removed_citations": removed,
        "removed_mentions": removed_mentions,
    }


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_stream(services: Services, plan: ChatPlan) -> AsyncIterator[str]:
    """Eventos SSE na ordem: sources -> token* -> done (ou error)."""
    timings = dict(plan.timings)
    filt = gr.CitationStreamFilter(plan.k, enabled=_strip_enabled(plan))
    error: str | None = None
    emitted: list[str] = []
    removed_mentions: list[str] = []
    yield sse("sources", {"sources": plan.sources})
    try:
        if plan.refused:
            yield sse("token", {"t": gr.REFUSAL_TEXT})
        else:
            t_llm = time.perf_counter()
            async for piece in services.llm.stream(plan.llm_messages or [], temperature=0.1):
                text = filt.feed(piece)
                if text:
                    emitted.append(text)
                    yield sse("token", {"t": text})
            tail = filt.flush()
            if tail:
                emitted.append(tail)
                yield sse("token", {"t": tail})
            timings["llm"] = _ms(t_llm)
            if plan.mentions is not None:
                # No streaming os tokens já saíram: as menções inválidas são só reportadas no `done`
                _, removed_mentions = plan.mentions.apply("".join(emitted))
        timings["total"] = _ms(plan.started)
        yield sse("done", {
            "timings_ms": timings, "refused": plan.refused,
            "removed_citations": filt.removed, "removed_mentions": removed_mentions,
        })
    except LLMError as exc:
        # LLM frio/indisponível: avisa com `error` antes de fechar o stream
        error = str(exc)
        yield sse("error", llm_unavailable())
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        yield sse("error", {"error": "internal", "retry": False, "message": "Erro inesperado ao gerar a resposta."})
    finally:
        timings.setdefault("total", _ms(plan.started))
        _log(
            services, "chat_stream", plan.cfg, plan.question,
            retrieval=plan.retrieval, timings_ms=timings, refused=plan.refused,
            removed_citations=filt.removed, removed_mentions=removed_mentions,
            input_truncated=plan.truncated, error=error,
        )


# --------------------------------------------------------------------------- #
# /triage
# --------------------------------------------------------------------------- #
async def _triage_llm(services: Services, msgs: list[dict[str, str]]) -> tuple[Any, str | None]:
    """Chama o LLM em modo JSON; se não validar, tenta mais uma vez com correção."""
    raw = await services.llm.complete(msgs, temperature=0.1, json_mode=True)
    try:
        return gr.parse_triage_json(raw), None
    except ValueError as first_error:  # JSONDecodeError e ValidationError são ValueError
        retry = msgs + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": triage_correction(str(first_error))},
        ]
    raw = await services.llm.complete(retry, temperature=0.1, json_mode=True)
    try:
        return gr.parse_triage_json(raw), None
    except ValueError as second_error:
        return None, f"JSON inválido do modelo após 2 tentativas: {second_error}"


def _empty_triage(cfg: RagConfig, timings: dict[str, int], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "labels": [], "component": None, "related": [], "docs": [], "needs_more_info": False,
        "explanation": "", "sources": [], "removed": {"labels": [], "related": [], "docs": [], "citations": [], "mentions": []},
        "rag": cfg.rag, "config": cfg.model_dump(), "timings_ms": timings, "refused": False, "error": None,
    }
    base.update(overrides)
    return base


async def triage_once(services: Services, title: str, body: str, cfg: RagConfig, endpoint: str = "triage") -> dict[str, Any]:
    started = time.perf_counter()
    cfg = effective_config(services, cfg, "triage")
    title, _ = gr.cap_input(title.strip(), 1000)
    body_clean = clean_issue_body(body)
    query, truncated = gr.cap_input(f"{title}\n{body_clean}".strip())
    body_for_llm = query[len(title) + 1 :] if query.startswith(title) else body_clean

    result: RetrievalResult | None = None
    hits = None
    timings: dict[str, int] = {}
    if cfg.rag:
        result = await run_retrieval(services, query, cfg)
        timings = {"retrieval": result.timings_ms.get("retrieval", 0), "rerank": result.timings_ms.get("rerank", 0)}
        if cfg.guardrails and not gr.passes_min_score(result, services.settings.min_score):
            timings["total"] = _ms(started)
            _log(services, endpoint, cfg, query, retrieval=result, timings_ms=timings, refused=True, input_truncated=truncated)
            return _empty_triage(cfg, timings, refused=True, explanation=gr.REFUSAL_TEXT)
        hits = result.hits

    msgs = triage_messages(services.prompts, title, body_for_llm, hits, services.labels, strict=cfg.guardrails)
    t_llm = time.perf_counter()
    try:
        output, error = await _triage_llm(services, msgs)
    except LLMError as exc:
        _log(services, endpoint, cfg, query, retrieval=result, error=str(exc))
        raise
    timings["llm"] = _ms(t_llm)
    sources = [h.to_source(n) for n, h in enumerate(hits or [], start=1)]

    if output is None:
        timings["total"] = _ms(started)
        _log(services, endpoint, cfg, query, retrieval=result, timings_ms=timings, refused=True, error=error)
        return _empty_triage(cfg, timings, refused=True, error=error, sources=sources)

    # Guardrails ligados: as três camadas (gate, prompt estrito, validação de saída).
    # Desligados: nada é validado, pra comparação mostrar o modelo "cru".
    mentions = gr.MentionGuard(hits, [title, body]) if (cfg.guardrails and hits is not None) else None
    guarded = gr.guard_triage(output, hits or [], services.allowed_labels, enabled=cfg.guardrails, mention_guard=mentions)
    timings["total"] = _ms(started)
    _log(
        services, endpoint, cfg, query,
        retrieval=result, timings_ms=timings, refused=False, removed=guarded.removed, input_truncated=truncated,
    )
    return _empty_triage(
        cfg, timings,
        labels=guarded.labels,
        component=output.component,
        related=guarded.related,
        docs=guarded.docs,
        needs_more_info=output.needs_more_info,
        explanation=guarded.explanation,
        sources=sources,
        removed=guarded.removed,
    )


# --------------------------------------------------------------------------- #
# /compare
# --------------------------------------------------------------------------- #
async def compare(services: Services, req: CompareRequest) -> dict[str, Any]:
    async def run(cfg: RagConfig) -> dict[str, Any]:
        try:
            if req.mode == "triage":
                return await triage_once(services, req.title, req.body, cfg, endpoint="compare_triage")
            messages = req.messages or [Message(role="user", content=f"{req.title}\n\n{req.body}".strip())]
            return await chat_once(services, messages, cfg, endpoint="compare_chat")
        except ApiError as exc:
            return {"error": exc.message, "status": exc.status, "config": cfg.model_dump()}
        except LLMError:
            return llm_unavailable(status=503, config=cfg.model_dump())

    results = await asyncio.gather(*(run(cfg) for cfg in req.configs))
    return {"results": list(results)}
