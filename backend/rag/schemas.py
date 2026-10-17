"""Modelos Pydantic v2: requests, responses e o schema JSON que o LLM gera na triagem."""
from __future__ import annotations

import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IndexName = Literal["base", "enxuto", "base_extras", "logico"]
SearchMode = Literal["dense", "bm25", "hybrid"]
Confidence = Literal["alta", "media", "baixa"]


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class RagConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rag: bool = True
    index: IndexName = "base"
    search: SearchMode = "dense"
    reranker: bool = False
    guardrails: bool = True
    top_k: int | None = Field(default=None, ge=1, le=50)


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    config: RagConfig = Field(default_factory=RagConfig)
    stream: bool = False


class TriageRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    config: RagConfig = Field(default_factory=RagConfig)


class CompareRequest(BaseModel):
    title: str = ""
    body: str = ""
    messages: list[Message] | None = None  # opcional no modo chat
    configs: list[RagConfig] = Field(min_length=1, max_length=4)
    mode: Literal["chat", "triage"] = "triage"


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class Source(BaseModel):
    n: int
    id: str
    doc_id: str
    source: str            # "issue #119", "pr #600" ou o doc_id
    number: int | None     # número da issue/PR, se houver
    type: str
    title: str
    url: str
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    rag: bool
    config: RagConfig
    timings_ms: dict[str, int]
    refused: bool
    removed_citations: list[int] = Field(default_factory=list)
    removed_mentions: list[str] = Field(default_factory=list)


class TriageLabel(BaseModel):
    name: str
    confidence: Confidence


class RelatedItem(BaseModel):
    n: int
    doc_id: str
    type: str
    number: int | None
    title: str
    url: str
    state: str
    reason: str
    score: float


class DocItem(BaseModel):
    n: int
    doc_id: str
    type: str
    title: str
    url: str


class TriageResponse(BaseModel):
    labels: list[TriageLabel] = Field(default_factory=list)
    component: str | None = None
    related: list[RelatedItem] = Field(default_factory=list)
    docs: list[DocItem] = Field(default_factory=list)
    needs_more_info: bool = False
    explanation: str = ""
    sources: list[Source] = Field(default_factory=list)
    removed: dict[str, list[Any]] = Field(default_factory=dict)
    rag: bool = True
    config: RagConfig
    timings_ms: dict[str, int] = Field(default_factory=dict)
    refused: bool = False
    error: str | None = None


# --------------------------------------------------------------------------- #
# Schema que o LLM devolve na triagem (a API completa o resto)
# --------------------------------------------------------------------------- #
def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


class LLMLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    confidence: Confidence = "media"

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> Any:
        # "Média" -> "media", "HIGH" continua inválido (força a correção)
        return _strip_accents(str(value)).strip().lower() if value is not None else "media"


class LLMRelated(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n: int | None = None
    id: str | None = None  # alguns modelos devolvem o doc_id em vez do número
    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_doc_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("id") is None and data.get("doc_id"):
            data = {**data, "id": data["doc_id"]}
        return data

    @model_validator(mode="after")
    def _needs_reference(self) -> "LLMRelated":
        if self.n is None and not self.id:
            raise ValueError("related precisa de 'n'")
        return self


class LLMDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n: int

    @model_validator(mode="before")
    @classmethod
    def _accept_int(cls, data: Any) -> Any:
        return {"n": data} if isinstance(data, int) else data


class TriageLLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    labels: list[LLMLabel] = Field(default_factory=list)
    component: str | None = None
    related: list[LLMRelated] = Field(default_factory=list)
    docs: list[LLMDoc] = Field(default_factory=list)
    needs_more_info: bool = False
    explanation: str = ""
