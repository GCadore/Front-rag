"""Reescrita da consulta (QUERY_REWRITE) e votação de labels (TRIAGE_LABEL_VOTES)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from rag.label_votes import majority, vote
from rag.query_rewrite import clean_rewrite, rewrite_messages, rewrite_query
from rag.schemas import RagConfig, TriageLLMOutput

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True}


def tri(labels: list[str], expl: str = "ok [1]", related: list[int] | None = None) -> str:
    return json.dumps({
        "labels": [{"name": n, "confidence": "alta"} for n in labels],
        "related": [{"n": n, "reason": "r"} for n in (related or [])], "docs": [], "explanation": expl,
    })


def out(labels: list[str], expl: str = "x") -> TriageLLMOutput:
    return TriageLLMOutput.model_validate(json.loads(tri(labels, expl)))


# ----------------------------- votação ----------------------------------- #
def test_vote_keeps_labels_in_majority_and_best_matching_sample() -> None:
    outs = [out(["type:bug", "area:catalog"], "a"), out(["type:bug", "area:scaffolder"], "b"), out(["type:bug", "area:catalog", "integration:github"], "c")]
    merged, votes = vote(outs)
    assert [lb.name for lb in merged.labels] == ["type:bug", "area:catalog"]
    assert votes == {"type:bug": 3, "area:catalog": 2, "area:scaffolder": 1, "integration:github": 1}
    assert merged.explanation == "a"  # amostra com labels idênticas ao resultado
    assert majority(3) == 2 and majority(2) == 2 and majority(1) == 1


def test_vote_can_return_no_labels_when_samples_disagree() -> None:
    merged, votes = vote([out(["type:bug"]), out(["type:suggestion"]), out(["type:feature"])])
    assert merged.labels == [] and sum(votes.values()) == 3


def test_triage_label_votes_per_request(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [tri(["type:bug", "area:scaffolder"]), tri(["type:bug"]), tri(["type:bug", "area:scaffolder", "integration:github"])]
    res = client.post("/triage", json={"title": "Scaffolder fails with GitHub app auth token", "config": {**RAG_CFG, "label_votes": 3}}).json()
    assert [lb["name"] for lb in res["labels"]] == ["type:bug", "area:scaffolder"]
    assert res["label_votes"]["type:bug"] == 3 and res["config"]["label_votes"] == 3
    assert len([c for c in fake_llm.calls if c.get("json_mode")]) == 3  # sem complete_n: 3 chamadas


def test_triage_votes_skip_invalid_samples_and_default_is_off(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = ["não é json", tri(["type:bug"]), tri(["type:bug", "area:catalog"])]
    res = client.post("/triage", json={"title": "Catalog bug", "config": {**RAG_CFG, "label_votes": 3}}).json()
    assert [lb["name"] for lb in res["labels"]] == ["type:bug"]  # 2 válidas -> precisa das 2
    fake_llm.calls.clear()
    fake_llm.json_replies = [tri(["type:bug"])]
    res = client.post("/triage", json={"title": "Catalog bug", "config": RAG_CFG}).json()
    assert res["label_votes"] is None and res["config"]["label_votes"] == 1
    assert len([c for c in fake_llm.calls if c.get("json_mode")]) == 1


def test_openai_client_complete_n_uses_single_request() -> None:
    from rag.llm import OpenAICompatLLM

    seen: dict = {}

    async def create(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"<think>x</think>{i}")) for i in range(kw["n"])])

    llm = OpenAICompatLLM.__new__(OpenAICompatLLM)
    llm.model, llm.timeout_s, llm.max_tokens, llm.extra_body = "m", 5.0, 64, {}
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert asyncio.run(llm.complete_n([{"role": "user", "content": "x"}], 3, temperature=0.7, json_mode=True)) == ["0", "1", "2"]
    assert seen["n"] == 3 and seen["temperature"] == 0.7 and seen["response_format"] == {"type": "json_object"}


# ----------------------------- reescrita --------------------------------- #
def test_clean_rewrite_and_messages() -> None:
    assert clean_rewrite('Query: "scaffolder github auth fails"\nmore') == "scaffolder github auth fails"
    assert clean_rewrite("   \n") == ""
    msgs = rewrite_messages("T", "b" * 5000)
    assert msgs[0]["role"] == "system" and len(msgs[1]["content"]) < 4100


def test_rewrite_query_swallows_llm_errors(fake_llm) -> None:
    fake_llm.answer = "scaffolder template github"
    assert asyncio.run(rewrite_query(fake_llm, "t", "b")) == "scaffolder template github"
    fake_llm.fail = True
    assert asyncio.run(rewrite_query(fake_llm, "t", "b")) is None


def test_retrieve_with_alt_query_modes(services) -> None:
    r = services.retriever
    cfg = RagConfig(index="base", search="dense", top_k=5)
    plain = r.retrieve("scaffolder template", cfg, 5)
    same = r.retrieve("scaffolder template", cfg, 5, alt_query="scaffolder template")
    assert [h.id for h in same.hits] == [h.id for h in plain.hits]  # reescrita igual = sem efeito
    repl = r.retrieve("zzzz qqqq", cfg, 5, alt_query="scaffolder template", alt_mode="replace")
    assert [h.id for h in repl.hits] == [h.id for h in plain.hits]  # replace = só a reescrita
    fused = r.retrieve("zzzz qqqq", cfg, 5, alt_query="scaffolder template", alt_mode="fuse", alt_lists="both")
    assert fused.hits and fused.relevance >= repl.relevance - 1e-9


def test_triage_query_rewrite_per_request(client: TestClient, fake_llm) -> None:
    fake_llm.answer = "scaffolder github app auth token"
    fake_llm.json_replies = [tri(["type:bug"])]
    res = client.post("/triage", json={"title": "Scaffolder fails", "body": "logs...", "config": {**RAG_CFG, "query_rewrite": True}}).json()
    assert res["search_query"] == "scaffolder github app auth token" and res["config"]["query_rewrite"] is True
    assert "rewrite" in res["timings_ms"]
    off = client.post("/triage", json={"title": "Scaffolder fails", "config": RAG_CFG}).json()
    assert off["search_query"] is None and off["config"]["query_rewrite"] is False


def test_rewrite_and_votes_settings_from_env(monkeypatch) -> None:
    from rag.settings import load_settings

    s = load_settings()
    assert s.query_rewrite is False and s.triage_label_votes == 1
    assert (s.query_rewrite_mode, s.query_rewrite_weight, s.query_rewrite_lists) == ("fuse", 0.5, "dense")
    monkeypatch.setenv("QUERY_REWRITE", "true")
    monkeypatch.setenv("QUERY_REWRITE_MODE", "replace")
    monkeypatch.setenv("TRIAGE_LABEL_VOTES", "3")
    monkeypatch.setenv("TRIAGE_VOTE_TEMPERATURE", "0.5")
    s = load_settings()
    assert s.query_rewrite is True and s.query_rewrite_mode == "replace" and s.triage_label_votes == 3 and s.triage_vote_temperature == 0.5
