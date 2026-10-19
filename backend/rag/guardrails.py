"""Guardrails de entrada e saída (seção 7 da spec)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

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


# --------------------------------------------------------------------------- #
# Citações fora do formato [n]
# O contexto chega como "[3] (issue #20753) título", e o modelo às vezes mistura:
# escreve [issue #3] (número do trecho), [issue #28190] (número real da issue),
# [#3], [doc-...], [1, 3] ou [issue nova]. Normalizamos tudo para [n] antes dos
# guardrails e da contagem de trechos usados.
# --------------------------------------------------------------------------- #
BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,80})\](?!\()")  # (?!\() pula links markdown [texto](url)
REF_RE = re.compile(r"^(?:(?:issue|pr|pull request|pull|doc|adr|trecho|fonte|source)\s*)?#?\s*(\d+)$", re.I)
SELF_REF_RE = re.compile(r"^(?:issue|pergunta)\s+(?:nova|atual)$|^nova\s+issue$", re.I)
SELF_REF_TEXT = "(issue nova)"
MAX_BRACKET = 80


def _ref_to_n(token: str, hits: list[Hit]) -> int | None:
    """Um item de dentro dos colchetes -> número do trecho (ou o número cru, se não achar)."""
    token = token.strip()
    by_doc = {h.doc_id: n for n, h in enumerate(hits, start=1)}
    by_chunk = {cid: n for n, h in enumerate(hits, start=1) for cid in (h.chunk_ids or [h.id])}
    if token in by_doc or token in by_chunk:
        return by_doc.get(token) or by_chunk.get(token)
    m = REF_RE.match(token)
    if not m:
        return None
    value = int(m.group(1))
    has_prefix = token[0] in "#" or token[0].isalpha()
    if has_prefix:  # "issue #28190" / "#600": primeiro tenta o número real da issue/PR
        for n, h in enumerate(hits, start=1):
            if h.number == value:
                return n
    return value  # "issue #3" / "3": número do trecho (fora de 1..k vira citação inválida)


# No texto corrido o modelo também escreve "a issue #3 também relata..." usando o número
# do TRECHO como se fosse o da issue (o trecho 3 é a #20753). O primeiro ramo casa um
# colchete inteiro só para pulá-lo: o que está entre colchetes é tratado em normalize_citations.
INDEX_MENTION_RE = re.compile(r"\[[^\[\]\n]*\]|(?<![\w#/])(issues?|PRs?|pull requests?)\s*#\s*(\d{1,3})(?!\d)", re.I)
USER_HASH_RE = re.compile(r"#(\d+)")


def fix_index_mentions(text: str, hits: list[Hit], user_texts: Iterable[str] = ()) -> tuple[str, int]:
    """Troca "issue #K" (K = número de trecho) pela referência real do trecho K.
    Não mexe se K for o número real de algum trecho, se aparecer no texto do usuário
    ou se estiver fora de 1..k."""
    if not hits:
        return text, 0
    real_numbers = {h.number for h in hits if h.number is not None}
    user_numbers = {int(m) for t in user_texts for m in USER_HASH_RE.findall(t or "")}
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(1) is None:  # era um [colchete]: fica como está
            return match.group(0)
        word, k = match.group(1), int(match.group(2))
        if not 1 <= k <= len(hits) or k in real_numbers or k in user_numbers:
            return match.group(0)
        hit = hits[k - 1]
        changed += 1
        if hit.number is None:  # doc/ADR não tem número: cita pelo título
            title = str(hit.metadata.get("title") or hit.doc_id)
            return f"doc “{title}” [{k}]"
        if str(hit.metadata.get("type", "")) == "pr":
            word = "PR"
        elif word.lower().startswith("pr") or word.lower().startswith("pull"):
            word = "issue"
        return f"{word} #{hit.number}"

    return INDEX_MENTION_RE.sub(repl, text), changed


def normalize_citations(text: str, hits: list[Hit], user_texts: Iterable[str] = ()) -> tuple[str, int]:
    """Reescreve citações fora do formato para [n] e corrige "issue #K" no texto corrido
    quando K é o número de um trecho. Retorna (texto, quantas foram reescritas).
    Sem trechos (modo sem RAG) não mexe em nada: não há a que mapear."""
    changed = 0
    if not hits:
        return text, 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        content = match.group(1).strip()
        if content.isdigit():
            return match.group(0)
        parts = [p for p in re.split(r"\s*(?:,|;|\be\b|\band\b)\s*", content) if p]
        self_ref = any(SELF_REF_RE.match(p) for p in parts)
        ns = [_ref_to_n(p, hits) for p in parts if not SELF_REF_RE.match(p)]
        if (not ns and not self_ref) or any(n is None for n in ns):
            return match.group(0)  # não é citação (texto entre colchetes, checkbox, [ref] etc.)
        changed += 1
        refs = "".join(f"[{n}]" for n in dict.fromkeys(ns))
        if self_ref:  # ex.: [issue nova, issue #3] -> "(issue nova) [3]"
            return SELF_REF_TEXT + (f" {refs}" if refs else "")
        return refs

    text = BRACKET_RE.sub(repl, text)
    text, fixed = fix_index_mentions(text, hits, user_texts)
    return text, changed + fixed


class CitationStreamFilter:
    """Versão em streaming: segura um '[...' incompleto até fechar o colchete,
    normaliza o formato e (com guardrails) remove citações inválidas."""

    def __init__(
        self, k: int, enabled: bool = True, hits: list[Hit] | None = None, user_texts: Iterable[str] = ()
    ):
        self.k = k
        self.enabled = enabled
        self.hits = hits or []
        self.user_texts = list(user_texts)
        self.buffer = ""
        self.removed: list[int] = []

    def _split_safe(self) -> tuple[str, str]:
        # Segura um '[' no final que ainda pode virar citação (ex.: "[1", " [issue #")
        match = re.search(r"\s?\[[^\[\]\n]*$", self.buffer)
        if match and len(self.buffer) - match.start() <= MAX_BRACKET + 2:
            return self.buffer[: match.start()], self.buffer[match.start() :]
        # Segura a última palavra, que pode ser o começo de "issue #3" ainda incompleto
        match = re.search(r"(?:[A-Za-z]+\s*)?#?\s*\d*$", self.buffer)
        if match and match.start() < len(self.buffer) and len(self.buffer) - match.start() <= 40:
            return self.buffer[: match.start()], self.buffer[match.start() :]
        return self.buffer, ""

    def _clean(self, text: str) -> str:
        text, _ = normalize_citations(text, self.hits, self.user_texts)
        if not self.enabled:
            return text
        cleaned, removed = strip_invalid_citations(text, self.k)
        self.removed.extend(n for n in removed if n not in self.removed)
        return cleaned

    def feed(self, chunk: str) -> str:
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


def related_from_hit(n: int, hit: Hit, reason: str) -> dict[str, Any]:
    """Preenche url/título/tipo SEMPRE pelos metadados, nunca pelo que o modelo escreveu."""
    meta = hit.metadata
    return {
        "n": n,
        "doc_id": hit.doc_id,
        "type": str(meta.get("type", "")),
        "number": hit.number,  # docs/ADRs têm number=-1 no índice; Hit.number devolve None
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
    user_texts: Iterable[str] = (),
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

    # O formato é sempre normalizado; remover citações inválidas é papel dos guardrails
    res.explanation, _ = normalize_citations(output.explanation, hits, user_texts)
    if enabled:
        res.explanation, res.removed["citations"] = strip_invalid_citations(res.explanation, len(hits))
        if mention_guard is not None:
            res.explanation, res.removed["mentions"] = mention_guard.apply(res.explanation)
    return res
