"""Testes mínimos da seção 10 da spec + SSE, /compare e guardrails."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rag.guardrails import REFUSAL_TEXT

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True, "top_k": 8}


def chat(client: TestClient, question: str, **cfg) -> dict:
    resp = client.post("/chat", json={"messages": [{"role": "user", "content": question}],
                                      "config": {**RAG_CFG, **cfg}, "stream": False})
    assert resp.status_code == 200, resp.text
    return resp.json()


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


# --------------------------- seção 10 ------------------------------------- #
def test_chat_with_rag_returns_sources(client: TestClient) -> None:
    data = chat(client, "Como funciona o Scaffolder?")
    assert data["sources"], "esperava trechos recuperados"
    assert data["rag"] is True and data["refused"] is False
    first = data["sources"][0]
    assert set(first) == {"n", "id", "doc_id", "source", "number", "type", "title", "url", "snippet", "score"}
    assert "scaffolder" in first["doc_id"] or "21034" in first["doc_id"]
    assert data["config"]["top_k"] == 8


def test_chat_without_rag_has_empty_sources(client: TestClient, fake_llm) -> None:
    data = chat(client, "Como funciona o Scaffolder?", rag=False)
    assert data["sources"] == []
    assert data["rag"] is False
    assert "CONTEXTO" not in fake_llm.calls[-1]["messages"][-1]["content"]


def test_triage_never_returns_invented_labels_or_related(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [json.dumps({
        "labels": [{"name": "area:scaffolder", "confidence": "alta"},
                   {"name": "area:inexistente", "confidence": "média"},
                   {"name": "priority:critical", "confidence": "baixa"}],
        "component": "scaffolder",
        "related": [{"n": 1, "reason": "mesmo erro"}, {"n": 42, "reason": "inventado"},
                    {"id": "issue-999999", "reason": "inventado"}],
        "docs": [{"n": 2}, {"n": 77}],
        "needs_more_info": False,
        "explanation": "Parece o mesmo erro [1][55].",
    })]
    resp = client.post("/triage", json={"title": "Scaffolder fails with GitHub app auth",
                                        "body": "<!-- template -->\n### Steps\n\n- [ ] li o guia\nerro de token",
                                        "config": {k: v for k, v in RAG_CFG.items() if k != "top_k"}})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    allowed = {lb["name"] for lb in client.get("/labels").json()}
    assert data["labels"] and all(lb["name"] in allowed for lb in data["labels"])
    assert "area:inexistente" in data["removed"]["labels"]
    assert "priority:critical" in data["removed"]["labels"]

    by_n = {s["n"]: s for s in data["sources"]}
    assert data["related"], "o related válido deveria ficar"
    for rel in data["related"]:
        assert rel["n"] in by_n and rel["doc_id"] == by_n[rel["n"]]["doc_id"]
        assert rel["url"] == by_n[rel["n"]]["url"]  # url veio dos metadados
    assert "issue-999999" in data["removed"]["related"]
    assert "[42]" in data["removed"]["related"]
    assert "[55]" not in data["explanation"] and 55 in data["removed"]["citations"]
    assert data["config"]["top_k"] == 10


def test_off_topic_question_is_refused(client: TestClient, fake_llm) -> None:
    data = chat(client, "receita de bolo")
    assert data["refused"] is True
    assert data["answer"] == REFUSAL_TEXT
    assert data["sources"] == []
    assert fake_llm.calls == []  # não chamou o LLM


def test_missing_api_key_returns_401(client: TestClient) -> None:
    body = {"messages": [{"role": "user", "content": "oi"}], "config": RAG_CFG}
    assert client.post("/chat", json=body, headers={"x-api-key": ""}).status_code == 401
    client.headers.pop("x-api-key")
    assert client.post("/chat", json=body).status_code == 401
    assert client.get("/labels").status_code == 401
    assert client.post("/triage", json={"title": "x"}).status_code == 401
    assert client.get("/health").status_code == 200  # /health não exige chave


# --------------------------- extras --------------------------------------- #
def test_health_lists_indices(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data == {"status": "ok", "indices": ["base", "logico"], "llm": "qwen2.5:7b", "reranker": False}


def test_labels_filtered_for_triage(client: TestClient) -> None:
    names = [lb["name"] for lb in client.get("/labels").json()]
    assert names == ["area:scaffolder", "area:catalog", "type:bug", "integration:github", "needs:repro"]


def test_chat_strips_invalid_citations(client: TestClient) -> None:
    data = chat(client, "Como funciona o Scaffolder?")
    assert "[9]" not in data["answer"] and "[1]" in data["answer"]
    assert data["removed_citations"] == [9]


def test_chat_stream_event_order(client: TestClient) -> None:
    body = {"messages": [{"role": "user", "content": "Como funciona o Scaffolder?"}], "config": RAG_CFG, "stream": True}
    with client.stream("POST", "/chat", json=body) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = "".join(resp.iter_text())
    events = parse_sse(text)
    names = [e for e, _ in events]
    assert names[0] == "sources" and names[-1] == "done"
    assert set(names[1:-1]) == {"token"}
    assert events[0][1]["sources"]
    answer = "".join(d["t"] for e, d in events if e == "token")
    assert "[9]" not in answer and "[1]" in answer
    assert events[-1][1]["removed_citations"] == [9]
    assert events[-1][1]["refused"] is False


def test_chat_stream_llm_error_event(client: TestClient, fake_llm) -> None:
    fake_llm.fail = True
    body = {"messages": [{"role": "user", "content": "Como funciona o Scaffolder?"}], "config": RAG_CFG, "stream": True}
    with client.stream("POST", "/chat", json=body) as resp:
        events = parse_sse("".join(resp.iter_text()))
    assert [e for e, _ in events] == ["sources", "error"]
    assert events[-1][1]["error"] == "llm_unavailable" and events[-1][1]["retry"] is True


def test_llm_unavailable_returns_503(client: TestClient, fake_llm) -> None:
    fake_llm.fail = True
    resp = client.post("/chat", json={"messages": [{"role": "user", "content": "Como funciona o Scaffolder?"}],
                                      "config": RAG_CFG})
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "llm_unavailable" and body["retry"] is True


def test_unknown_index_returns_400(client: TestClient) -> None:
    resp = client.post("/chat", json={"messages": [{"role": "user", "content": "Scaffolder"}],
                                      "config": {**RAG_CFG, "index": "enxuto"}})
    assert resp.status_code == 400


def test_triage_retries_invalid_json_once(client: TestClient, fake_llm) -> None:
    good = json.dumps({"labels": [{"name": "type:bug", "confidence": "alta"}], "explanation": "ok [1]"})
    fake_llm.json_replies = ["isto não é json", good]
    data = client.post("/triage", json={"title": "Scaffolder fails", "config": RAG_CFG}).json()
    assert data["refused"] is False and data["labels"] == [{"name": "type:bug", "confidence": "alta"}]
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[1]["messages"][-1]["role"] == "user"  # mensagem de correção


def test_triage_refuses_after_two_invalid_json(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = ['{"labels": "errado"}']
    data = client.post("/triage", json={"title": "Scaffolder fails", "config": RAG_CFG}).json()
    assert data["refused"] is True and data["error"]
    assert len(fake_llm.calls) == 2


def test_compare_runs_configs_in_parallel(client: TestClient) -> None:
    resp = client.post("/compare", json={
        "mode": "chat", "title": "Como funciona o Scaffolder?", "body": "",
        "configs": [RAG_CFG, {**RAG_CFG, "rag": False}, {**RAG_CFG, "index": "enxuto"}],
    })
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    assert results[0]["sources"] and results[0]["rag"] is True
    assert results[1]["sources"] == [] and results[1]["rag"] is False
    assert results[2]["status"] == 400 and "error" in results[2]


def test_compare_triage_mode(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [json.dumps({"labels": [{"name": "area:scaffolder", "confidence": "alta"}]})]
    resp = client.post("/compare", json={"mode": "triage", "title": "Scaffolder fails with GitHub app auth",
                                         "configs": [RAG_CFG, {**RAG_CFG, "guardrails": False}]})
    results = resp.json()["results"]
    assert [r["labels"][0]["name"] for r in results] == ["area:scaffolder", "area:scaffolder"]


def test_compare_rejects_more_than_four_configs(client: TestClient) -> None:
    resp = client.post("/compare", json={"mode": "chat", "title": "x", "configs": [RAG_CFG] * 5})
    assert resp.status_code == 422


def test_requests_are_logged(client: TestClient, settings) -> None:
    chat(client, "Como funciona o Scaffolder?")
    lines = settings.log_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["endpoint"] == "chat"
    assert record["retrieved"] and record["config"]["index"] == "base"
    assert record["removed_citations"] == [9] and "total" in record["timings_ms"]


# --------------------------- menções a issues/PRs/URLs --------------------- #
HALLUCINATED = ("Veja a issue #21034 [1] e também #99999, "
                "https://github.com/backstage/backstage/pull/88888 e https://exemplo.inventado.com/x. "
                "Docs: https://backstage.io/docs/features/software-templates/")


def test_chat_removes_unknown_mentions(client: TestClient, fake_llm) -> None:
    fake_llm.answer = HALLUCINATED
    data = chat(client, "Scaffolder fails with GitHub App auth")
    assert "#21034" in data["answer"]                       # existe nos trechos
    assert "software-templates" in data["answer"]           # URL dos metadados
    assert "#99999" not in data["answer"] and "88888" not in data["answer"]
    assert "inventado" not in data["answer"]
    assert set(data["removed_mentions"]) == {
        "#99999", "https://github.com/backstage/backstage/pull/88888", "https://exemplo.inventado.com/x"}


def test_chat_stream_reports_unknown_mentions_in_done(client: TestClient, fake_llm) -> None:
    fake_llm.answer = "Parecido com #99999 [1]."
    body = {"messages": [{"role": "user", "content": "Como funciona o Scaffolder?"}], "config": RAG_CFG, "stream": True}
    with client.stream("POST", "/chat", json=body) as resp:
        events = parse_sse("".join(resp.iter_text()))
    assert events[-1][0] == "done" and events[-1][1]["removed_mentions"] == ["#99999"]


def test_mentions_kept_without_guardrails_and_from_user_question(client: TestClient, fake_llm) -> None:
    fake_llm.answer = "Sobre a #99999 e a #77777."
    data = chat(client, "O que houve na #77777 do scaffolder?")
    assert "#77777" in data["answer"] and data["removed_mentions"] == ["#99999"]
    data = chat(client, "Como funciona o Scaffolder?", guardrails=False)
    assert "#99999" in data["answer"] and data["removed_mentions"] == []


def test_triage_removes_unknown_mentions(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [json.dumps({
        "labels": [{"name": "area:scaffolder", "confidence": "alta"}],
        "explanation": "Mesmo erro da #21034 [1] e da #99999.",
    })]
    data = client.post("/triage", json={"title": "Scaffolder fails with GitHub app auth", "config": RAG_CFG}).json()
    assert "#21034" in data["explanation"] and "#99999" not in data["explanation"]
    assert data["removed"]["mentions"] == ["#99999"]
