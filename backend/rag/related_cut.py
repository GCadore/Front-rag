"""Corte de related por score (RELATED_MIN_SCORE).

O LLM escolhe os related entre os trechos do CONTEXTO; aqui tiramos os que vieram de trechos com
score de busca baixo. Tipos de score (RELATED_SCORE_KIND):
  dense    cosseno do trecho com a consulta (escala absoluta; trecho só do BM25 conta como 0)
  rrf_rel  score do RRF dividido pelo melhor score do contexto (0..1, relativo à consulta)
Limiar <= 0 desliga o corte (útil para desligar por requisição quando o servidor liga).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .retrieval import Hit

KINDS = ("dense", "rrf_rel")


def related_score(hit: "Hit", hits: list["Hit"], kind: str = "dense") -> float:
    if kind == "rrf_rel":
        top = max((h.score for h in hits), default=0.0)
        return float(hit.score) / top if top > 0 else 0.0
    return float(hit.dense_score) if hit.dense_score is not None else 0.0


def cut_related(
    related: list[dict[str, Any]], hits: list["Hit"], threshold: float | None, kind: str = "dense"
) -> tuple[list[dict[str, Any]], list[str]]:
    """Devolve (related mantidos, doc_ids cortados). Itens sem `n` válido passam sem corte."""
    if threshold is None or threshold <= 0 or not hits:
        return related, []
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for item in related:
        n = item.get("n")
        if not isinstance(n, int) or not 1 <= n <= len(hits):
            kept.append(item)
            continue
        if related_score(hits[n - 1], hits, kind) >= threshold:
            kept.append(item)
        else:
            removed.append(str(item.get("doc_id") or f"[{n}]"))
    return kept, removed
