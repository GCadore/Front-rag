"""Votação de labels na triagem (TRIAGE_LABEL_VOTES).

O LLM gera a triagem N vezes (temperatura ~0.7, numa requisição só com `n=N` quando o cliente
suporta) e ficam as labels que aparecem em pelo menos `min_votes` amostras (padrão: maioria).
Os outros campos (related, docs, explicação...) vêm da amostra cujas labels mais se parecem com
o resultado da votação, para a explicação continuar coerente com as labels.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .schemas import TriageLLMOutput


def majority(n: int) -> int:
    return n // 2 + 1


def label_names(output: TriageLLMOutput) -> list[str]:
    seen: list[str] = []
    for lb in output.labels:
        name = lb.name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def vote(outputs: list[TriageLLMOutput], min_votes: int | None = None) -> tuple[TriageLLMOutput, dict[str, int]]:
    """Junta as amostras válidas. Devolve (saída com as labels votadas, votos por label)."""
    if not outputs:
        raise ValueError("sem amostras para votar")
    need = min_votes if min_votes is not None else majority(len(outputs))
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for out in outputs:
        for pos, name in enumerate(label_names(out)):
            counts[name] += 1
            first_seen.setdefault(name, len(first_seen) * 100 + pos)
    winners = [n for n in sorted(counts, key=lambda n: (-counts[n], first_seen[n])) if counts[n] >= need]

    def jaccard(out: TriageLLMOutput) -> float:
        a, b = set(label_names(out)), set(winners)
        return len(a & b) / len(a | b) if a | b else 1.0

    best = max(range(len(outputs)), key=lambda i: (jaccard(outputs[i]), -i))
    base = outputs[best]
    conf: dict[str, Any] = {}
    for out in [base] + outputs:
        for lb in out.labels:
            conf.setdefault(lb.name.strip(), lb.confidence)
    labels = [{"name": n, "confidence": conf.get(n, "media")} for n in winners]
    merged = TriageLLMOutput.model_validate({**base.model_dump(), "labels": labels})
    return merged, {n: counts[n] for n in sorted(counts, key=lambda n: (-counts[n], first_seen[n]))}
