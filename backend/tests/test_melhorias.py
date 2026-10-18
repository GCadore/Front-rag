"""Ajudas de precisão da triagem: labels dos vizinhos (A), descrições + exemplos (B) e citação de docs."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rag.prompts import format_context, triage_messages, PromptStore
from rag.retrieval import Hit
from rag.triage_aids import label_description, neighbor_labels, parse_cutoff

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True}
CUT = parse_cutoff("2026-04-22T00:00:00Z")
OK_TRIAGE = json.dumps({"labels": [{"name": "type:bug", "confidence": "alta"}], "related": [], "docs": [], "explanation": "ok [1]"})


def hit(doc_id: str, kind: str, number, title: str, labels: str = "", created=1_700_000_000) -> Hit:
    meta = {"type": kind, "number": number, "title": title, "labels": labels, "created_at": created, "doc_id": doc_id}
    return Hit(id=f"{doc_id}-000", doc_id=doc_id, text="x", metadata=meta, score=1.0)


def test_neighbors_take_real_labels_of_similar_issues_and_prs() -> None:
    hits = [
        hit("doc-a", "doc", -1, "Doc A"),
        hit("issue-1", "issue", 1, "Scaffolder quebra", "type:bug|area:scaffolder|needs:triage|integration:github"),
        hit("issue-1", "issue", 1, "Scaffolder quebra", "type:bug|area:scaffolder"),  # 2º trecho do mesmo doc
        hit("pr-2", "pr", 2, "fix scaffolder", "area:scaffolder"),
    ]
    nb = neighbor_labels(hits, "Nova issue", CUT)
    assert [n["doc_id"] for n in nb] == ["issue-1", "pr-2"]
    assert nb[0]["n"] == 2 and nb[0]["labels"] == ["type:bug", "area:scaffolder", "integration:github"]  # sem needs:*
    assert nb[0]["ref"] == "issue #1"


def test_neighbors_leakage_guard_excludes_self_and_post_cutoff() -> None:
    hits = [
        hit("issue-9", "issue", 9, "🐛 Swagger UI deep linking not working", "type:bug|area:catalog"),  # a própria issue
        hit("issue-8", "issue", 8, "Outra", "type:bug|area:catalog", created=CUT + 10),  # depois do corte
        hit("issue-7", "issue", 7, "Antiga", "type:suggestion|area:catalog", created=CUT - 10),
    ]
    nb = neighbor_labels(hits, "Swagger UI deep linking not working", CUT)
    assert [n["doc_id"] for n in nb] == ["issue-7"]
    assert len(neighbor_labels(hits, "Swagger UI deep linking not working", None)) == 2  # corte desligado
    assert parse_cutoff("") is None


def test_neighbors_respect_k() -> None:
    hits = [hit(f"issue-{i}", "issue", i, f"t{i}", "type:bug") for i in range(1, 9)]
    assert len(neighbor_labels(hits, "x", CUT, k=5)) == 5


def test_label_descriptions_fill_missing_and_vague() -> None:
    assert "GitHub" in label_description({"name": "integration:github", "description": ""})
    assert "catalog-info" in label_description({"name": "area:catalog", "description": "Related to the Catalog Project Area"})
    assert label_description({"name": "type:bug", "description": "Something isn't working at all here"}) == "Something isn't working at all here"


def test_prompt_includes_aids_only_when_enabled() -> None:
    labels = [{"name": "integration:github", "description": ""}]
    hits = [hit("issue-1", "issue", 1, "t", "type:bug|integration:github")]
    nb = neighbor_labels(hits, "x", CUT)
    off = triage_messages(PromptStore(None, {}), "x", "y", hits, labels, strict=True)[1]["content"]
    on = triage_messages(PromptStore(None, {}), "x", "y", hits, labels, strict=True, neighbors=nb, label_descriptions=True)[1]["content"]
    assert "LABELS DAS ISSUES" not in off and "EXEMPLOS RESOLVIDOS" not in off and "- integration:github\n" in off + "\n"
    assert "LABELS DAS ISSUES" in on and "[1] issue #1: type:bug, integration:github" in on
    assert "EXEMPLOS RESOLVIDOS" in on and "integration:github: Envolve GitHub" in on


def test_doc_citation_uses_doc_id_not_minus_one() -> None:
    h = hit("doc-features/techdocs/README", "doc", -1, "TechDocs")
    src = h.to_source(1)
    assert src["source"] == "doc-features/techdocs/README" and src["number"] is None
    assert "#-1" not in format_context([h])
    assert hit("adr-012", "adr", "", "ADR").to_source(1)["source"] == "adr-012"
    assert hit("issue-5", "issue", 5, "x").to_source(1)["source"] == "issue #5"


def test_triage_api_toggles_per_request_and_defaults(client: TestClient, fake_llm, services) -> None:
    store = services.retriever.indices["base"].store
    store["issue-21034-000"].metadata.update({"labels": "type:bug|area:scaffolder|integration:github", "created_at": 1_600_000_000})
    fake_llm.json_replies = [OK_TRIAGE]
    body = {"title": "Scaffolder fails with GitHub app auth token"}
    on = client.post("/triage", json={**body, "config": RAG_CFG}).json()
    prompt_on = fake_llm.calls[-1]["messages"][1]["content"]
    assert on["config"]["neighbor_labels"] is True and on["config"]["label_descriptions"] is True
    assert any(n["doc_id"] == "issue-21034" for n in on["neighbor_labels"])
    assert "LABELS DAS ISSUES" in prompt_on and "EXEMPLOS RESOLVIDOS" in prompt_on
    off = client.post("/triage", json={**body, "config": {**RAG_CFG, "neighbor_labels": False, "label_descriptions": False}}).json()
    prompt_off = fake_llm.calls[-1]["messages"][1]["content"]
    assert off["neighbor_labels"] is None and "LABELS DAS ISSUES" not in prompt_off and "EXEMPLOS RESOLVIDOS" not in prompt_off


def test_triage_aids_env_defaults(monkeypatch) -> None:
    from rag.settings import load_settings
    monkeypatch.setenv("TRIAGE_NEIGHBOR_LABELS", "false")
    monkeypatch.setenv("TRIAGE_LABEL_DESCRIPTIONS", "0")
    monkeypatch.setenv("TRIAGE_NEIGHBOR_CUTOFF", "")
    s = load_settings()
    assert s.triage_neighbor_labels is False and s.triage_label_descriptions is False and s.triage_neighbor_cutoff == ""
