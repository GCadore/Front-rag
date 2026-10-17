"""Prompts de sistema e montagem das mensagens para o LLM.

Os textos padrão estão aqui; para editar sem mexer no código, crie/edite
`prompts/<nome>.txt` (ou `PROMPTS_DIR`) ou a chave `prompts.<nome>` do config.yaml.
Nomes: chat_strict, chat_simple, triage_strict, triage_simple, triage_schema.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .retrieval import Hit

DEFAULT_PROMPTS: dict[str, str] = {
    # Seção 7 da spec (guardrails=true)
    "chat_strict": (
        "Você é um assistente de triagem de issues do repositório backstage/backstage.\n"
        "Responda SOMENTE com base nos trechos fornecidos em CONTEXTO, numerados [1]..[k].\n"
        "Cite o número do trecho em toda afirmação, assim: [2].\n"
        "Se o contexto não tiver a resposta, diga que não encontrou na base. "
        "Não invente issues, PRs, links, versões ou labels.\n"
        "Responda em português."
    ),
    # guardrails=false ou rag=false: prompt simples, sem as regras
    "chat_simple": "Você é um assistente que responde perguntas sobre o Backstage (backstage.io). Responda em português.",
    "triage_strict": (
        "Você é um assistente de triagem de issues do repositório backstage/backstage.\n"
        "Use SOMENTE os trechos fornecidos em CONTEXTO, numerados [1]..[k].\n"
        "Escolha labels SOMENTE da lista LABELS PERMITIDAS. Cite trechos na explicação, assim: [2].\n"
        "Em related e docs, use apenas números de trechos que existem no CONTEXTO.\n"
        "Não invente issues, PRs, links, versões ou labels. Escreva a explicação em português."
    ),
    "triage_simple": "Você ajuda a fazer a triagem de issues do repositório backstage/backstage. Escreva em português.",
    "triage_schema": (
        "Responda APENAS com um objeto JSON neste formato, sem texto fora do JSON:\n"
        '{"labels": [{"name": "string", "confidence": "alta|media|baixa"}],\n'
        ' "component": "string|null",\n'
        ' "related": [{"n": 1, "reason": "string"}],\n'
        ' "docs": [{"n": 3}],\n'
        ' "needs_more_info": false,\n'
        ' "explanation": "string com citações [n]"}'
    ),
}

HISTORY_LIMIT = 6  # mensagens anteriores incluídas no prompt do /chat


class PromptStore:
    def __init__(self, prompts_dir: Path | None = None, config: dict[str, Any] | None = None):
        self._prompts = dict(DEFAULT_PROMPTS)
        overrides = (config or {}).get("prompts") or {}
        if isinstance(overrides, dict):
            self._prompts.update({k: str(v).strip() for k, v in overrides.items() if v})
        if prompts_dir and prompts_dir.is_dir():
            for path in prompts_dir.glob("*.txt"):
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    self._prompts[path.stem] = text

    def get(self, name: str) -> str:
        return self._prompts[name]


def format_context(hits: list["Hit"]) -> str:
    blocks = []
    for n, hit in enumerate(hits, start=1):
        meta = hit.metadata
        number = meta.get("number")
        ref = f"{meta.get('type', '')} #{number}" if number not in (None, "") else str(meta.get("type", ""))
        header = f"[{n}] ({ref}) {meta.get('title', '')} - {meta.get('url', '')}".strip()
        blocks.append(f"{header}\n{hit.text.strip()}")
    return "\n\n".join(blocks)


def chat_messages(
    prompts: PromptStore,
    question: str,
    history: list[dict[str, str]],
    hits: list["Hit"] | None,
    strict: bool,
) -> list[dict[str, str]]:
    """Monta as mensagens do /chat. `hits=None` = modo sem RAG."""
    system = prompts.get("chat_strict" if strict and hits is not None else "chat_simple")
    msgs = [{"role": "system", "content": system}]
    msgs.extend(history[-HISTORY_LIMIT:])
    if hits is None:
        user = question
    else:
        context = format_context(hits) or "(nenhum trecho encontrado)"
        user = f"CONTEXTO:\n{context}\n\nPERGUNTA: {question}"
    msgs.append({"role": "user", "content": user})
    return msgs


def triage_messages(
    prompts: PromptStore,
    title: str,
    body: str,
    hits: list["Hit"] | None,
    labels: list[dict[str, Any]],
    strict: bool,
) -> list[dict[str, str]]:
    system = prompts.get("triage_strict" if strict else "triage_simple") + "\n\n" + prompts.get("triage_schema")
    label_lines = "\n".join(
        f"- {lb['name']}" + (f": {lb['description']}" if lb.get("description") else "") for lb in labels
    )
    parts = [f"LABELS PERMITIDAS:\n{label_lines}"]
    if hits is not None:
        parts.append(f"CONTEXTO:\n{format_context(hits) or '(nenhum trecho encontrado)'}")
    parts.append(f"ISSUE NOVA:\nTítulo: {title}\n\n{body}")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def triage_correction(error: str) -> str:
    return (
        "Sua resposta anterior não passou na validação do schema: "
        f"{error[:800]}\nResponda novamente APENAS com o objeto JSON no formato pedido."
    )
