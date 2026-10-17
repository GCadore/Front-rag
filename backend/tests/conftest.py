"""Fakes para rodar os testes sem GPU, modelos ou dados reais.

- FakeEmbedder: bag-of-words com hash -> vetor normalizado (o resto do
  retrieval é o código de verdade: NumpyDense, diversidade, merge, cap).
- FakeLLM: respostas roteirizadas, sem rede.
"""
from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path
from typing import Any, AsyncIterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import create_app  # noqa: E402
from rag.guardrails import filter_triage_labels  # noqa: E402
from rag.indices import Chunk, Index, NumpyDense  # noqa: E402
from rag.llm import LLMError  # noqa: E402
from rag.pipeline import Services  # noqa: E402
from rag.prompts import PromptStore  # noqa: E402
from rag.reqlog import RequestLogger  # noqa: E402
from rag.retrieval import Retriever  # noqa: E402
from rag.settings import Settings  # noqa: E402

API_KEY = "test-key"
DIM = 512
STOPWORDS = {"como", "funciona", "o", "a", "de", "do", "da", "com", "e", "que", "para", "em", "um", "uma", "the", "with"}

CHUNKS = [
    Chunk("doc-scaffolder-000", "[DOC] Scaffolder\n\nO Scaffolder cria componentes a partir de templates do scaffolder.",
          {"type": "doc", "doc_id": "doc-scaffolder", "title": "Software Templates", "chunk_index": 0,
           "url": "https://backstage.io/docs/features/software-templates/"}),
    Chunk("doc-scaffolder-001", "Cada template do scaffolder define parâmetros e ações (actions) do scaffolder.",
          {"type": "doc", "doc_id": "doc-scaffolder", "title": "Software Templates", "chunk_index": 1,
           "url": "https://backstage.io/docs/features/software-templates/"}),
    Chunk("issue-21034-000", "[ISSUE #21034] Scaffolder fails with GitHub App auth\n\nscaffolder github app auth erro token",
          {"type": "issue", "doc_id": "issue-21034", "number": 21034, "state": "closed", "chunk_index": 0,
           "title": "Scaffolder fails with GitHub App auth", "url": "https://github.com/backstage/backstage/issues/21034"}),
    Chunk("issue-500-000", "[ISSUE #500] Catalog não processa entidades\n\ncatalog entidades processing",
          {"type": "issue", "doc_id": "issue-500", "number": 500, "state": "open", "chunk_index": 0,
           "title": "Catalog não processa entidades", "url": "https://github.com/backstage/backstage/issues/500"}),
    Chunk("pr-600-000", "[PR #600] techdocs build mkdocs\n\ntechdocs mkdocs build",
          {"type": "pr", "doc_id": "pr-600", "number": 600, "state": "merged", "chunk_index": 0,
           "title": "techdocs build", "url": "https://github.com/backstage/backstage/pull/600"}),
]

# Índice "logico": outro conjunto de chunks, pra testar a troca de índice
LOGICO_CHUNKS = [
    Chunk("adr-012-000", "[ADR 012] Scaffolder executa templates em tarefas isoladas do scaffolder",
          {"type": "adr", "doc_id": "adr-012", "title": "ADR 012: Scaffolder tasks", "chunk_index": 0,
           "url": "https://backstage.io/docs/architecture-decisions/adrs-adr012"}),
    Chunk("issue-777-000", "[ISSUE #777] Scaffolder logico template erro\n\nscaffolder template erro",
          {"type": "issue", "doc_id": "issue-777", "number": 777, "state": "open", "chunk_index": 0,
           "title": "Scaffolder template erro", "url": "https://github.com/backstage/backstage/issues/777"}),
]

LABELS_RAW = [
    {"name": "area:scaffolder", "description": "", "color": "x"},
    {"name": "area:catalog", "description": "", "color": "x"},
    {"name": "type:bug", "description": "", "color": "x"},
    {"name": "integration:github", "description": "", "color": "x"},
    {"name": "needs:repro", "description": "", "color": "x"},
    {"name": "needs:triage", "description": "", "color": "x"},
    {"name": "priority:critical", "description": "", "color": "x"},
]


class FakeEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for tok in re.findall(r"\w+", text.lower()):
                if tok not in STOPWORDS:
                    out[row, zlib.crc32(tok.encode()) % DIM] += 1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out


class FakeLLM:
    model = "fake-llm"

    def __init__(self) -> None:
        self.answer = "O Scaffolder cria componentes a partir de templates [1]. Veja também [9]."
        self.json_replies: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    async def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.1, json_mode: bool = False) -> str:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        if self.fail:
            raise LLMError("conexão recusada")
        if json_mode:
            return self.json_replies.pop(0) if len(self.json_replies) > 1 else self.json_replies[0]
        return self.answer

    async def stream(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> AsyncIterator[str]:
        self.calls.append({"messages": messages, "stream": True})
        if self.fail:
            raise LLMError("conexão recusada")
        for i in range(0, len(self.answer), 3):  # pedaços pequenos para testar o filtro de citações
            yield self.answer[i : i + 3]


def build_fake_index(embedder: FakeEmbedder, name: str = "base", chunks: list[Chunk] | None = None) -> Index:
    chunks = chunks if chunks is not None else CHUNKS
    store = {c.id: c for c in chunks}
    matrix = embedder.encode([c.text for c in chunks])
    return Index(name, store, NumpyDense([c.id for c in chunks], matrix), bm25=None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        rag_api_key=API_KEY,
        enable_reranker=False,
        log_path=tmp_path / "logs" / "requests.jsonl",
        prompts_dir=tmp_path / "no-prompts",
        min_score={"dense": 0.2, "rerank": 0.0, "bm25": 0.0},
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def services(settings: Settings, fake_llm: FakeLLM) -> Services:
    embedder = FakeEmbedder()
    indices = {
        "base": build_fake_index(embedder),
        "logico": build_fake_index(embedder, "logico", LOGICO_CHUNKS),
    }
    retriever = Retriever(settings, indices, embedder, reranker=None)
    return Services(
        settings=settings,
        retriever=retriever,
        llm=fake_llm,
        labels=filter_triage_labels(LABELS_RAW),
        prompts=PromptStore(None, {}),
        request_log=RequestLogger(settings.log_path),
    )


@pytest.fixture
def client(services: Services) -> TestClient:
    with TestClient(create_app(services)) as c:
        c.headers.update({"x-api-key": API_KEY})
        yield c
