"""API do Backstage RAG (FastAPI). Rodar: `uvicorn api:app --port 8000` dentro de backend/.

Spec: backend/API_SPEC.md.
"""
from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from rag.guardrails import filter_triage_labels
from rag.llm import LLMError
from rag.pipeline import ApiError, Services, chat_once, chat_stream, compare, llm_unavailable, plan_chat, triage_once
from rag.prompts import PromptStore
from rag.reqlog import RequestLogger
from rag.schemas import ChatRequest, ChatResponse, CompareRequest, TriageRequest, TriageResponse
from rag.settings import BACKEND_DIR, Settings, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


# --------------------------------------------------------------------------- #
# Inicialização
# --------------------------------------------------------------------------- #
def labels_candidates(settings: Settings) -> list[Path]:
    paths = [settings.labels_path] if settings.labels_path else []
    paths += [
        settings.data_dir.parent / "labels.json",
        Path("data") / "labels.json",
        BACKEND_DIR.parent / "data" / "labels.json",
    ]
    return paths


def load_labels(settings: Settings) -> list[dict[str, Any]]:
    for path in labels_candidates(settings):
        if path.is_file():
            log.info("Labels carregadas de %s", path)
            return filter_triage_labels(json.loads(path.read_text(encoding="utf-8")))
    log.warning("labels.json não encontrado; /labels vai sair vazio")
    return []


def build_services(settings: Settings | None = None) -> Services:
    """Carrega tudo de verdade: modelos e índices UMA vez."""
    from rag.indices import build_retriever  # import tardio (numpy/chroma/torch)
    from rag.llm import OpenAICompatLLM

    settings = settings or load_settings()
    if not settings.rag_api_key:
        log.warning("RAG_API_KEY vazio: todas as rotas protegidas vão responder 401")
    return Services(
        settings=settings,
        retriever=build_retriever(settings),
        # Timeout vem de LLM_TIMEOUT_S (300 no Modal): na partida a frio a 1ª pergunta espera em vez de dar erro
        llm=OpenAICompatLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout_s),
        labels=load_labels(settings),
        prompts=PromptStore(settings.prompts_dir, settings.config),
        request_log=RequestLogger(settings.log_path),
    )


def create_app(services: Services | None = None, settings: Settings | None = None) -> FastAPI:
    """`services` permite injetar fakes nos testes; sem ele, o lifespan carrega tudo."""
    settings = services.settings if services else (settings or load_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services or build_services(settings)
        yield

    app = FastAPI(title="Backstage RAG API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-api-key"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
        # LLM frio (partida a frio no Modal) ou fora do ar: o cliente pode tentar de novo
        log.error("Erro no LLM: %s", exc)
        return JSONResponse(status_code=503, content=llm_unavailable(), headers={"Retry-After": "30"})

    register_routes(app)
    return app


# --------------------------------------------------------------------------- #
# Dependências
# --------------------------------------------------------------------------- #
def get_services(request: Request) -> Services:
    return request.app.state.services


def require_api_key(
    x_api_key: str | None = Header(default=None), services: Services = Depends(get_services)
) -> None:
    expected = services.settings.rag_api_key
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="x-api-key ausente ou inválido")


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #
def register_routes(app: FastAPI) -> None:
    auth = [Depends(require_api_key)]

    @app.get("/health")
    async def health(services: Services = Depends(get_services)) -> dict[str, Any]:
        indices = services.available_indices
        return {
            "status": "ok" if indices else "degraded",
            "indices": indices,
            "llm": services.settings.llm_model,
            "reranker": bool(services.retriever and services.retriever.has_reranker),
        }

    @app.get("/labels", dependencies=auth)
    async def labels(services: Services = Depends(get_services)) -> list[dict[str, Any]]:
        return services.labels

    @app.post("/chat", dependencies=auth, response_model=ChatResponse)
    async def chat(req: ChatRequest, services: Services = Depends(get_services)) -> Any:
        if not req.stream:
            return await chat_once(services, req.messages, req.config)
        # Retrieval antes de abrir o stream: erros 400/503 saem como HTTP normal
        plan = await plan_chat(services, req.messages, req.config)
        return StreamingResponse(
            chat_stream(services, plan),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/triage", dependencies=auth, response_model=TriageResponse)
    async def triage(req: TriageRequest, services: Services = Depends(get_services)) -> Any:
        return await triage_once(services, req.title, req.body, req.config)

    @app.post("/compare", dependencies=auth)
    async def compare_route(req: CompareRequest, services: Services = Depends(get_services)) -> dict[str, Any]:
        return await compare(services, req)


app = create_app()
