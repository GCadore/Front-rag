"""Reescrita da consulta da triagem (QUERY_REWRITE).

Antes da busca, o LLM resume a issue (título + corpo, sem logs/templates) numa consulta curta.
A consulta reescrita entra no RRF junto com a original (modo "fuse", padrão) ou no lugar dela
("replace"). O prompt da triagem continua recebendo a issue inteira: só a busca muda.
Qualquer falha do LLM aqui é engolida: a busca segue só com a consulta original.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLM

REWRITE_SYSTEM = (
    "You turn a GitHub issue from the backstage/backstage repository into a short search query for a hybrid "
    "(BM25 + embeddings) search over Backstage issues, pull requests and docs.\n"
    "Keep: plugin/package names (e.g. @backstage/plugin-catalog), components, APIs, config keys, CLI commands, "
    "the key error message (short, no stack trace) and the core problem in a few words.\n"
    "Drop: logs, stack traces, code dumps, issue-template headings and checklists, environment/version boilerplate, "
    "greetings and opinions.\n"
    "Answer with ONE line in English, 8 to 40 words, no quotes, no labels, no explanation."
)
MAX_BODY_CHARS = 4000
MAX_QUERY_CHARS = 400


def rewrite_messages(title: str, body: str, max_body_chars: int = MAX_BODY_CHARS) -> list[dict[str, str]]:
    body = (body or "").strip()[:max_body_chars]
    return [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": f"Title: {title.strip()}\n\nBody:\n{body}"},
    ]


def clean_rewrite(text: str) -> str:
    """Primeira linha não vazia, sem aspas/prefixos tipo 'Query:', no máximo MAX_QUERY_CHARS."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    out = re.sub(r"^(search\s+)?query\s*:\s*", "", lines[0], flags=re.IGNORECASE)
    out = out.strip().strip("\"'`").strip()
    return out[:MAX_QUERY_CHARS].strip()


async def rewrite_query(llm: "LLM", title: str, body: str) -> str | None:
    """Consulta reescrita, ou None se o LLM falhar ou devolver vazio."""
    try:
        raw = await llm.complete(rewrite_messages(title, body), temperature=0.0)
    except Exception:  # noqa: BLE001 - reescrita é opcional
        return None
    return clean_rewrite(raw) or None
