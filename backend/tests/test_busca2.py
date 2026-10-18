"""Busca 2: top-k separado por tipo, BM25 com título/labels reforçados e corte de related por score."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rag import indices as ix
from rag.indices import Chunk, boosted_text
from rag.related_cut import cut_related, related_score
from rag.retrieval import Hit, split_by_type
from rag.schemas import RagConfig

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True}


def h(cid: str, kind: str, score: float, dense: float | None = None) -> Hit:
    doc = cid.rsplit("-", 1)[0]
    return Hit(id=cid, doc_id=doc, text=cid, metadata={"type": kind}, score=score, dense_score=dense)


# ------------------------------ split por tipo ------------------------------ #
def test_split_by_type_takes_k_from_each_group_in_rank_order() -> None:
    cands = [h(f"issue-{i}-000", "issue", 10 - i) for i in range(8)] + [h("doc-a-000", "doc", 1.0), h("adr-1-000", "adr", 0.5)]
    sel = split_by_type(cands, 6, 4, 2, lambda r, x: True)
    assert [x.id for x in sel] == ["issue-0-000", "issue-1-000", "issue-2-000", "issue-3-000", "doc-a-000", "adr-1-000"]


def test_split_by_type_fills_shortfall_from_other_group_and_scales_k() -> None:
    cands = [h(f"issue-{i}-000", "issue", 10 - i) for i in range(8)] + [h("doc-a-000", "doc", 1.0)]
    sel = split_by_type(cands, 10, 5, 5, lambda r, x: True)
    assert len(sel) == 9 and sum(x.metadata["type"] == "doc" for x in sel) == 1  # só 1 doc: issues completam
    sel = split_by_type(cands, 4, 5, 5, lambda r, x: True)  # top_k=4 -> 2 + 2 (proporcional)
    assert [x.metadata["type"] for x in sel].count("issue") == 3  # só 1 doc: a 2ª vaga de doc vai para issue


def test_retrieve_split_types_per_request(services) -> None:
    cfg_on = RagConfig(index="base", search="dense", top_k=4, split_types=True)
    cfg_off = RagConfig(index="base", search="dense", top_k=4)
    on = services.retriever.retrieve("scaffolder template github", cfg_on, 4)
    off = services.retriever.retrieve("scaffolder template github", cfg_off, 4)
    assert on.hits and off.hits
    assert any(x.metadata.get("type") in ("doc", "adr") for x in on.hits)


# ------------------------------ BM25 reforçado ------------------------------ #
def test_boosted_text_repeats_title_and_labels_only_for_issues_prs() -> None:
    meta = {"type": "issue", "title": "Catalog breaks", "labels": "type:bug|area:catalog|needs:triage"}
    c = Chunk("issue-1-000", "[ISSUE #1] Catalog breaks | labels: type:bug\n\nbody", meta)
    out = boosted_text(c, 2, 1)
    assert out.count("Catalog breaks") == 3 and "type bug area catalog" in out and "needs" not in out.split("\n", 1)[1]
    doc = Chunk("doc-x-000", "doc text", {"type": "doc", "title": "Doc"})
    assert boosted_text(doc, 3, 3) == "doc text"
    assert boosted_text(c, 0, 0) == c.text


def test_build_boosted_bm25_uses_same_ids_and_boosted_texts(monkeypatch) -> None:
    seen = {}

    def fake_build(texts, ids, tokenizer, settings):
        seen["texts"], seen["ids"] = texts, ids
        return "boosted"

    monkeypatch.setattr(ix, "build_bm25", fake_build)
    store = {"issue-1-000": Chunk("issue-1-000", "t", {"type": "issue", "title": "Hello"}), "doc-a-000": Chunk("doc-a-000", "d", {"type": "doc"})}
    plain = type("P", (), {"ids": ["issue-1-000", "doc-a-000", "gone-000"]})()
    index = ix.Index("base", store, None, plain)
    assert ix.build_boosted_bm25(index, None, None, 1, 0) == "boosted"
    assert seen["ids"] == ["issue-1-000", "doc-a-000"] and seen["texts"][0].count("Hello") == 1 and seen["texts"][1] == "d"
    assert ix.build_boosted_bm25(index, None, None, 0, 0) is None


def test_retrieve_uses_boosted_bm25_only_when_asked(services, monkeypatch) -> None:
    calls = []

    class FakeBM25:
        def __init__(self, tag):
            self.tag = tag

        def search(self, q, n):
            calls.append(self.tag)
            return [("issue-21034-000", 1.0)]

    index = services.retriever.indices["base"]
    monkeypatch.setattr(index, "bm25", FakeBM25("plain"))
    monkeypatch.setattr(index, "bm25_boost", FakeBM25("boost"), raising=False)
    services.retriever.retrieve("scaffolder", RagConfig(index="base", search="bm25", top_k=3), 3)
    services.retriever.retrieve("scaffolder", RagConfig(index="base", search="bm25", top_k=3, bm25_boost=True), 3)
    monkeypatch.setattr(services.settings, "bm25_boost", True)
    services.retriever.retrieve("scaffolder", RagConfig(index="base", search="bm25", top_k=3), 3)
    services.retriever.retrieve("scaffolder", RagConfig(index="base", search="bm25", top_k=3, bm25_boost=False), 3)
    assert calls == ["plain", "boost", "boost", "plain"]


# ------------------------------ corte de related ---------------------------- #
def test_cut_related_by_dense_and_relative_scores() -> None:
    hits = [h("issue-1-000", "issue", 0.04, 0.80), h("issue-2-000", "issue", 0.02, 0.50), h("doc-a-000", "doc", 0.01, None)]
    rel = [{"n": 1, "doc_id": "issue-1"}, {"n": 2, "doc_id": "issue-2"}, {"n": 3, "doc_id": "doc-a"}, {"n": 9, "doc_id": "x"}]
    kept, cut = cut_related(rel, hits, 0.6, "dense")
    assert [k["doc_id"] for k in kept] == ["issue-1", "x"] and cut == ["issue-2", "doc-a"]
    kept, cut = cut_related(rel, hits, 0.5, "rrf_rel")
    assert [k["doc_id"] for k in kept] == ["issue-1", "issue-2", "x"] and cut == ["doc-a"]
    assert cut_related(rel, hits, None)[0] == rel and cut_related(rel, hits, 0)[0] == rel
    assert related_score(hits[2], hits, "dense") == 0.0 and related_score(hits[1], hits, "rrf_rel") == 0.5


def test_triage_related_min_score_per_request(client: TestClient, fake_llm) -> None:
    reply = json.dumps({"labels": [{"name": "type:bug", "confidence": "alta"}],
                        "related": [{"n": 1, "reason": "a"}, {"n": 2, "reason": "b"}], "docs": [], "explanation": "ok [1]"})
    fake_llm.json_replies = [reply]
    body = {"title": "Scaffolder fails with GitHub app auth token", "body": "scaffolder github app auth erro token"}
    off = client.post("/triage", json={**body, "config": RAG_CFG}).json()
    on = client.post("/triage", json={**body, "config": {**RAG_CFG, "related_min_score": 0.99}}).json()
    assert len(off["related"]) == 2 and off["config"]["related_min_score"] is None
    assert len(on["related"]) < 2 and on["removed"]["related_score"] and on["config"]["related_min_score"] == 0.99


def test_busca2_settings_from_env(monkeypatch) -> None:
    from rag.settings import load_settings

    s = load_settings()
    assert (s.split_types, s.bm25_title_boost, s.bm25_label_boost, s.bm25_boost, s.related_min_score) == (False, 0, 0, False, None)
    for k, v in {"RETRIEVAL_SPLIT_TYPES": "true", "RETRIEVAL_SPLIT_K_ISSUES": "6", "RETRIEVAL_SPLIT_K_DOCS": "4",
                 "BM25_TITLE_BOOST": "2", "BM25_LABEL_BOOST": "1", "BM25_BOOST": "1", "RELATED_MIN_SCORE": "0.6",
                 "RELATED_SCORE_KIND": "rrf_rel"}.items():
        monkeypatch.setenv(k, v)
    s = load_settings()
    assert (s.split_types, s.split_k_issues, s.split_k_docs, s.bm25_title_boost, s.bm25_label_boost, s.bm25_boost) == (True, 6, 4, 2, 1, True)
    assert s.related_min_score == 0.6 and s.related_score_kind == "rrf_rel"
