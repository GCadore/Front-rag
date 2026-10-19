"""Citações fora do formato [n] (ex.: [issue #3], [issue #28190], [issue nova]) são normalizadas."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rag.guardrails import CitationStreamFilter, normalize_citations, related_from_hit, strip_invalid_citations
from rag.retrieval import Hit

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True, "top_k": 8}


def hit(doc_id: str, kind: str, number: int | None = None) -> Hit:
    meta = {"type": kind, "doc_id": doc_id, "title": doc_id, "url": f"https://x/{doc_id}"}
    if number is not None:
        meta["number"] = number
    return Hit(f"{doc_id}-000", doc_id, "texto", meta, score=0.5)


# Mesma ordem dos trechos da triagem real da #34395
HITS = [
    hit("issue-28190", "issue", 28190),
    hit("doc-integrations/gitlab/locations", "doc"),
    hit("issue-20753", "issue", 20753),
    hit("issue-29060", "issue", 29060),
    hit("pr-30123", "pr", 30123),
    hit("issue-30601", "issue", 30601),
]


def test_real_explanation_from_34395_is_normalized() -> None:
    text = (
        "A remoção de mode causa falhas 406 [issue nova]. Isso afeta o GitlabUrlReader [issue nova, issue #3]. "
        "O problema é consistente com a issue #28190 [issue #28190]. A issue #6 sugere retry [issue #6]."
    )
    out, changed = normalize_citations(text, HITS)
    assert changed == 5
    assert "falhas 406 (issue nova)." in out
    assert "GitlabUrlReader (issue nova) [3]." in out
    assert "issue #28190 [1]." in out        # número real da issue -> trecho 1
    assert "sugere retry [6]." in out          # "[issue #6]" -> trecho 6
    assert "A issue #30601 sugere" in out      # texto corrido: trecho 6 é a #30601
    assert "[issue" not in out


def test_other_citation_shapes() -> None:
    cases = {
        "ver [#3]": "ver [3]",
        "ver [1, 3]": "ver [1][3]",
        "ver [1 e 3]": "ver [1][3]",
        "ver [doc-integrations/gitlab/locations]": "ver [2]",
        "ver [PR #30123]": "ver [5]",
        "ver [trecho 4]": "ver [4]",
        "ver [issue #99999]": "ver [99999]",   # não está nos trechos: vira citação inválida
        "ver [3]": "ver [3]",
    }
    for given, expected in cases.items():
        assert normalize_citations(given, HITS)[0] == expected, given


def test_non_citations_are_untouched() -> None:
    text = "Veja [a doc](https://backstage.io/docs) e os [ref] mascarados; - [ ] tarefa; [x] feito; [sem relação]"
    out, changed = normalize_citations(text, HITS)
    assert out == text and changed == 0


def test_without_hits_nothing_changes() -> None:
    # Modo sem RAG: não há trechos, e as referências inventadas devem continuar visíveis na comparação
    text = "Corrigido na [issue #23001] [issue nova]"
    assert normalize_citations(text, []) == (text, 0)


def test_invalid_reference_is_removed_by_guardrails() -> None:
    text, _ = normalize_citations("Mesma causa [issue #28190] e [issue #99999].", HITS)
    cleaned, removed = strip_invalid_citations(text, len(HITS))
    assert cleaned == "Mesma causa [1] e." and removed == [99999]


def test_stream_filter_normalizes_split_brackets() -> None:
    chunks = ["Causa [iss", "ue #28", "190] e [issue #9", "9]. Fim [issue no", "va]."]
    on = CitationStreamFilter(len(HITS), enabled=True, hits=HITS)
    out = "".join(on.feed(c) for c in chunks) + on.flush()
    assert out == "Causa [1] e. Fim (issue nova)." and on.removed == [99]

    off = CitationStreamFilter(len(HITS), enabled=False, hits=HITS)
    out = "".join(off.feed(c) for c in chunks) + off.flush()
    assert out == "Causa [1] e [99]. Fim (issue nova)."   # sem guardrails: normaliza, não remove


def test_chat_answer_is_normalized(client: TestClient, fake_llm) -> None:
    fake_llm.answer = "Mesmo erro de auth [issue #21034]; ver também [issue nova]."
    data = client.post("/chat", json={"messages": [{"role": "user", "content": "Scaffolder fails with GitHub App auth"}],
                                      "config": RAG_CFG}).json()
    n = next(s["n"] for s in data["sources"] if s["doc_id"] == "issue-21034")
    assert f"Mesmo erro de auth [{n}];" in data["answer"]
    assert "(issue nova)" in data["answer"] and "[issue" not in data["answer"]
    assert data["removed_citations"] == []


def test_triage_explanation_is_normalized(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [json.dumps({
        "labels": [{"name": "area:scaffolder", "confidence": "alta"}],
        "explanation": "Mesmo erro da [issue #21034] [issue nova, issue #2] e [issue #99999].",
    })]
    data = client.post("/triage", json={"title": "Scaffolder fails with GitHub App auth", "config": RAG_CFG}).json()
    n = next(s["n"] for s in data["sources"] if s["doc_id"] == "issue-21034")
    assert data["explanation"].startswith(f"Mesmo erro da [{n}] (issue nova) [2]")
    assert "[issue" not in data["explanation"] and data["removed"]["citations"] == [99999]


# --------------------------- "issue #K" no texto corrido ------------------- #
def test_running_text_index_becomes_real_number() -> None:
    from rag.guardrails import fix_index_mentions

    text = "A issue #3 também relata o 406. O PR #5 corrige. Veja a Issue #4 e a issue #2."
    out, changed = fix_index_mentions(text, HITS)
    assert changed == 4
    assert "A issue #20753 também relata" in out          # trecho 3 é a #20753
    assert "O PR #30123 corrige" in out                   # trecho 5 é um PR
    assert "a Issue #29060" in out                        # mantém a maiúscula do modelo
    assert "a doc “doc-integrations/gitlab/locations” [2]" in out  # trecho 2 é doc: cita pelo título


def test_running_text_keeps_real_and_user_numbers() -> None:
    from rag.guardrails import fix_index_mentions

    hits = HITS + [hit("issue-4", "issue", 4)]            # a issue #4 existe nos trechos
    text = "Igual à issue #4, citada pelo usuário na issue #2; a issue #28190 e a issue #12 também."
    out, changed = fix_index_mentions(text, hits, user_texts=["isso parece a issue #2"])
    assert out == text and changed == 0                   # #4 real, #2 do usuário, #12 fora de 1..k


def test_running_text_ignores_brackets_links_and_no_rag() -> None:
    from rag.guardrails import fix_index_mentions

    text = "Ver [issue #3](https://github.com/backstage/backstage/issues/3) e github.com/x/issues/3."
    assert fix_index_mentions(text, HITS) == (text, 0)
    assert fix_index_mentions("A issue #3 relata", []) == ("A issue #3 relata", 0)


def test_stream_fixes_running_text_split_across_chunks() -> None:
    chunks = ["A iss", "ue #", "3 também relata; a issue #3", "0601 também [issue #", "6]."]
    filt = CitationStreamFilter(len(HITS), enabled=True, hits=HITS)
    out = "".join(filt.feed(c) for c in chunks) + filt.flush()
    assert out == "A issue #20753 também relata; a issue #30601 também [6]."


def test_triage_explanation_running_text(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [json.dumps({
        "labels": [{"name": "area:scaffolder", "confidence": "alta"}],
        "explanation": "A issue #1 descreve o mesmo erro de auth [1].",
    })]
    data = client.post("/triage", json={"title": "Scaffolder fails with GitHub App auth", "config": RAG_CFG}).json()
    first = data["sources"][0]
    expected = f"issue #{first['number']}" if first["number"] else f"doc “{first['title']}” [1]"
    assert data["explanation"].startswith(f"A {expected}")
    assert "issue #1 " not in data["explanation"]


def test_related_doc_without_number_returns_none() -> None:
    # Docs vêm do índice com number=-1; o front mostrava "#-1"
    assert related_from_hit(1, hit("doc-releases/v1.49.0", "doc", -1), "r")["number"] is None
    assert related_from_hit(1, hit("issue-19545", "issue", 19545), "r")["number"] == 19545
