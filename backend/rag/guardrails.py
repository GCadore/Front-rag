"""Guardrails de entrada e saída (seção 7 da spec)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .retrieval import Hit, RetrievalResult
from .schemas import TriageLLMOutput

MAX_INPUT_CHARS = 20_000
REFUSAL_TEXT = "Não encontrei nada sobre isso na base do Backstage."

TRIAGE_LABEL_PREFIXES = ("type:", "area:", "integration:", "domain:")
TRIAGE_LABEL_EXTRAS = {"needs:repro", "needs:more-info"}

CITATION_RE = re.compile(r"\s?\[(\d+)\]")


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #
def cap_input(text: str, limit: int = MAX_INPUT_CHARS) -> tuple[str, bool]:
    """Corta a entrada em 20 mil caracteres. Retorna (texto, foi_cortado)."""
    return (text[:limit], True) if len(text) > limit else (text, False)


def passes_min_score(result: RetrievalResult, min_score: dict[str, float | None]) -> bool:
    """Gate do MIN_SCORE. O limiar depende da escala do score (dense/bm25/rerank)."""
    if not result.hits:
        return False
    threshold = min_score.get(result.scorer)
    if threshold is None:  # sem limiar configurado
        return True
    if result.scorer == "bm25":
        return result.relevance > threshold
    return result.relevance >= threshold


def filter_triage_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        lb
        for lb in labels
        if str(lb.get("name", "")).startswith(TRIAGE_LABEL_PREFIXES) or lb.get("name") in TRIAGE_LABEL_EXTRAS
    ]


# --------------------------------------------------------------------------- #
# Saída: citações [n]
# --------------------------------------------------------------------------- #
def strip_invalid_citations(text: str, k: int) -> tuple[str, list[int]]:
    """Remove [n] com n fora de 1..k. Retorna (texto, números removidos)."""
    removed: list[int] = []

    def repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= k:
            return match.group(0)
        if n not in removed:
            removed.append(n)
        return ""

    return CITATION_RE.sub(repl, text), removed


class CitationStreamFilter:
    """Versão em streaming: segura um possível '[123' até fechar o colchete."""

    def __init__(self, k: int, enabled: bool = True):
        self.k = k
        self.enabled = enabled
        self.buffer = ""
        self.removed: list[int] = []

    def _split_safe(self) -> tuple[str, str]:
        # Segura um '[' no final que ainda pode virar citação (ex.: "[1" ou " [")
        match = re.search(r"\s?\[\d*$", self.buffer)
        if match and len(self.buffer) - match.start() <= 8:
            return self.buffer[: match.start()], self.buffer[match.start() :]
        return self.buffer, ""

    def _clean(self, text: str) -> str:
        cleaned, removed = strip_invalid_citations(text, self.k)
        self.removed.extend(n for n in removed if n not in self.removed)
        return cleaned

    def feed(self, chunk: str) -> str:
        if not self.enabled:
            return chunk
        self.buffer += chunk
        ready, self.buffer = self._split_safe()
        return self._clean(ready)

    def flush(self) -> str:
        out, self.buffer = self._clean(self.buffer), ""
        return out


# --------------------------------------------------------------------------- #
# Saída: menções a issues/PRs (#123, github.com/.../issues/123) e URLs
# Só ficam as que existem nos trechos recuperados (metadados ou texto) ou na
# própria pergunta do usuário. O resto é trocado por MENTION_MARKER.
# --------------------------------------------------------------------------- #
MENTION_MARKER = "(referência removida)"
GH_REF_RE = re.compile(r"https?://(?:www\.)?github\.com/backstage/backstage/(?:issues|pull)/(\d+)[^\s)\]>\"'`]*", re.I)
URL_RE = re.compile(r"https?://[^\s)\]>\"'`]+", re.I)
HASH_RE = re.compile(r"(?<![\w&/#])#(\d{2,7})\b")  # 2+ dígitos: evita "passo #1"


def _norm_url(url: str) -> str:
    return url.rstrip(".,;:!?").rstrip("/").lower()


@dataclass
class KnownRefs:
    numbers: set[int] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)

    def url_ok(self, url: str) -> bool:
        norm = _norm_url(url)
        return any(norm == u or u.startswith(norm + "/") or norm.startswith(u + "#") for u in self.urls)


def known_refs(hits: list[Hit], extra_texts: list[str] = ()) -> KnownRefs:  # type: ignore[assignment]
    """Números de issue/PR e URLs que podem ser citados com segurança."""
    refs = KnownRefs()
    texts = list(extra_texts)
    for hit in hits:
        meta = hit.metadata
        number = meta.get("number")
        if isinstance(number, int) or str(number).isdigit():
            refs.numbers.add(int(number))
        if meta.get("url"):
            refs.urls.add(_norm_url(str(meta["url"])))
        texts.append(hit.text)
    for text in texts:
        refs.numbers.update(int(m) for m in HASH_RE.findall(text))
        refs.numbers.update(int(m) for m in GH_REF_RE.findall(text))
        refs.urls.update(_norm_url(u) for u in URL_RE.findall(text))
    return refs


def strip_unknown_mentions(text: str, refs: KnownRefs) -> tuple[str, list[str]]:
    """Remove menções a issues/PRs/URLs que não estão nos trechos. Retorna (texto, removidas)."""
    removed: list[str] = []

    def drop(mention: str) -> str:
        if mention not in removed:
            removed.append(mention)
        return MENTION_MARKER

    def gh(match: re.Match[str]) -> str:
        url = match.group(0)
        ok = int(match.group(1)) in refs.numbers or refs.url_ok(url)
        return url if ok else drop(url.rstrip(".,;:!?")) + url[len(url.rstrip(".,;:!?")):]

    def any_url(match: re.Match[str]) -> str:
        url = match.group(0)
        if GH_REF_RE.fullmatch(url) or url == MENTION_MARKER:
            return url  # já tratado acima
        core = url.rstrip(".,;:!?")
        return url if refs.url_ok(core) else drop(core) + url[len(core):]

    def hashref(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) in refs.numbers else drop(match.group(0))

    text = GH_REF_RE.sub(gh, text)
    text = URL_RE.sub(any_url, text)
    text = HASH_RE.sub(hashref, text)
    return text, removed


class MentionGuard:
    """Agrupa o filtro de menções para /chat e /triage."""

    def __init__(self, hits: list[Hit], user_texts: list[str]):
        self.refs = known_refs(hits, user_texts)

    def apply(self, text: str) -> tuple[str, list[str]]:
        return strip_unknown_mentions(text, self.refs)


# --------------------------------------------------------------------------- #
# Saída: triagem
# --------------------------------------------------------------------------- #
def parse_triage_json(raw: str) -> TriageLLMOutput:
    """JSON -> Pydantic. Aceita resposta embrulhada em ```json ... ```."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return TriageLLMOutput.model_validate(json.loads(text))


@dataclass
class TriageGuarded:
    labels: list[dict[str, Any]] = field(default_factory=list)
    related: list[dict[str, Any]] = field(default_factory=list)
    docs: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    removed: dict[str, list[Any]] = field(default_factory=dict)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def related_from_hit(n: int, hit: Hit, reason: str) -> dict[str, Any]:
    """Preenche url/título/tipo SEMPRE pelos metadados, nunca pelo que o modelo escreveu."""
    meta = hit.metadata
    return {
        "n": n,
        "doc_id": hit.doc_id,
        "type": str(meta.get("type", "")),
        "number": _int_or_none(meta.get("number")),
        "title": str(meta.get("title", "")),
        "url": str(meta.get("url", "")),
        "state": str(meta.get("state", "")),
        "reason": reason,
        "score": round(float(hit.score), 4),
        "dense_score": None if hit.dense_score is None else round(float(hit.dense_score), 4),
    }


def _unchecked_related(rel: Any) -> dict[str, Any]:
    """Guardrails desligados: devolve o que o modelo escreveu, sem conferir nos trechos."""
    return {
        "n": rel.n if rel.n is not None else 0,
        "doc_id": rel.id or "",
        "type": "",
        "number": None,
        "title": "",
        "url": "",
        "state": "",
        "reason": rel.reason,
        "score": 0.0,
    }


def _doc_from_hit(n: int, hit: Hit) -> dict[str, Any]:
    return {
        "n": n,
        "doc_id": hit.doc_id,
        "type": str(hit.metadata.get("type", "")),
        "title": str(hit.metadata.get("title", "")),
        "url": str(hit.metadata.get("url", "")),
    }


def guard_triage(
    output: TriageLLMOutput,
    hits: list[Hit],
    allowed_labels: set[str],
    enabled: bool = True,
    mention_guard: MentionGuard | None = None,
) -> TriageGuarded:
    """Camada de saída da triagem. Com `enabled=False` (guardrails desligados) nada é
    validado nem removido: labels, related, docs e explicação saem como o modelo gerou."""
    res = TriageGuarded(removed={"labels": [], "related": [], "docs": [], "citations": [], "mentions": []})
    valid_n = lambda n: n is not None and 1 <= n <= len(hits)  # noqa: E731

    seen_labels: set[str] = set()
    for label in output.labels:
        name = label.name.strip()
        if name in seen_labels:
            continue
        if not enabled or name in allowed_labels:
            res.labels.append({"name": name, "confidence": label.confidence})
            seen_labels.add(name)
        else:
            res.removed["labels"].append(name)

    by_doc = {h.doc_id: n for n, h in enumerate(hits, start=1)}
    by_id = {cid: n for n, h in enumerate(hits, start=1) for cid in (h.chunk_ids or [h.id])}
    # Deduplica por documento: dois trechos não vizinhos da mesma issue (ex.: [1] e [3]
    # da #28190) viram um item só, o primeiro que o modelo citou.
    seen_related: set[str] = set()
    for rel in output.related:
        n = rel.n if valid_n(rel.n) else None
        if n is None and rel.id:
            n = by_doc.get(rel.id) or by_id.get(rel.id)
        if n is None:
            if enabled:
                res.removed["related"].append(rel.id or f"[{rel.n}]")
            else:
                res.related.append(_unchecked_related(rel))
            continue
        if hits[n - 1].doc_id not in seen_related:
            res.related.append(related_from_hit(n, hits[n - 1], rel.reason))
            seen_related.add(hits[n - 1].doc_id)

    seen_n: set[int] = set()
    seen_docs: set[str] = set()
    for doc in output.docs:
        if doc.n in seen_n:
            continue
        seen_n.add(doc.n)
        if valid_n(doc.n):
            if hits[doc.n - 1].doc_id in seen_docs:
                continue
            seen_docs.add(hits[doc.n - 1].doc_id)
            res.docs.append(_doc_from_hit(doc.n, hits[doc.n - 1]))
        elif enabled:
            res.removed["docs"].append(f"[{doc.n}]")
        else:
            res.docs.append({"n": doc.n, "doc_id": "", "type": "", "title": "", "url": ""})

    res.explanation = output.explanation
    if enabled:
        res.explanation, res.removed["citations"] = strip_invalid_citations(output.explanation, len(hits))
        if mention_guard is not None:
            res.explanation, res.removed["mentions"] = mention_guard.apply(res.explanation)
    return res
