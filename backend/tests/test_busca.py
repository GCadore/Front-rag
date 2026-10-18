"""RRF ponderado, agrupamento por documento e configuração da busca híbrida."""
from __future__ import annotations

from rag.retrieval import Hit, attach_doc_chunks, group_by_doc, order_by_doc, rrf_fuse


def h(cid: str, doc: str, score: float) -> Hit:
    return Hit(id=cid, doc_id=doc, text=cid, metadata={"type": "issue"}, score=score)


def test_rrf_classic_when_weights_equal() -> None:
    a = [("x", 1.0), ("y", 0.5)]
    b = [("y", 9.0), ("z", 1.0)]
    classic = [d for d, _ in rrf_fuse([a, b], k=60)]
    halves = [d for d, _ in rrf_fuse([a, b], k=60, weights=[0.5, 0.5])]
    assert classic == halves == ["y", "x", "z"]


def test_rrf_weight_favors_bm25() -> None:
    dense = [("d1", 0.9), ("d2", 0.8)]
    bm25 = [("b1", 9.0), ("b2", 8.0)]
    assert rrf_fuse([dense, bm25], k=30, weights=[0.2, 0.8])[0][0] == "b1"
    assert rrf_fuse([dense, bm25], k=30, weights=[0.8, 0.2])[0][0] == "d1"
    assert [d for d, _ in rrf_fuse([dense, bm25], k=30, weights=[1.0, 0.0])] == ["d1", "d2"]


def test_group_by_doc_keeps_best_chunk_per_doc() -> None:
    hits = [h("a-0", "a", 3), h("a-1", "a", 2), h("b-0", "b", 1.5), h("a-2", "a", 1), h("c-0", "c", 0.5)]
    assert [x.id for x in group_by_doc(hits)] == ["a-0", "b-0", "c-0"]


def test_search_settings_from_env(monkeypatch) -> None:
    from rag.settings import load_settings

    s = load_settings()
    assert s.rrf_w_bm25 == 0.8 and s.group_by_doc is False and s.rrf_k == 30 and s.chunks_per_doc == 3
    monkeypatch.setenv("RETRIEVAL_CHUNKS_PER_DOC", "2")
    assert load_settings().chunks_per_doc == 2
    monkeypatch.setenv("RRF_K", "60")
    monkeypatch.setenv("RRF_W_BM25", "0.5")
    monkeypatch.setenv("RETRIEVAL_GROUP_BY_DOC", "true")
    s = load_settings()
    assert s.rrf_k == 60 and s.rrf_w_bm25 == 0.5 and s.group_by_doc is True


def test_group_by_doc_in_retrieve_returns_distinct_docs(services, monkeypatch) -> None:
    from rag.schemas import RagConfig

    monkeypatch.setattr(services.settings, "group_by_doc", True)
    monkeypatch.setattr(services.settings, "chunks_per_doc", 1)
    res = services.retriever.retrieve("scaffolder template", RagConfig(index="base", search="dense", top_k=10), 10)
    docs = [x.doc_id for x in res.hits]
    assert len(docs) == len(set(docs))


def test_attach_doc_chunks_adds_best_chunks_round_robin() -> None:
    cands = [h("a-0", "a", 3), h("a-1", "a", 2.5), h("b-0", "b", 2), h("a-2", "a", 1.8), h("x-0", "x", 1.7),
             h("b-1", "b", 1.5), h("a-3", "a", 1.2), h("b-2", "b", 1.0)]
    docs = group_by_doc(cands)[:2]  # a, b (x fica de fora)
    out = attach_doc_chunks(docs, cands, 3)
    assert [x.id for x in out] == ["a-0", "b-0", "a-1", "b-1", "a-2", "b-2"]  # nunca a-3 nem x
    assert all(x.score == (3 if x.doc_id == "a" else 2) for x in out)  # extras herdam o score do doc
    assert attach_doc_chunks(docs, cands, 1) == docs


def test_attach_doc_chunks_respects_token_budget_and_keeps_all_docs() -> None:
    big = "palavra " * 200  # ~400 tokens
    cands = [Hit(id=f"{d}-{i}", doc_id=d, text=big, metadata={"type": "issue"}, score=10 - i)
             for d in "abc" for i in range(3)]
    docs = group_by_doc(cands)
    out = attach_doc_chunks(docs, cands, 3, max_tokens=1700)  # 3 docs (~1200) + 1 extra
    assert {x.doc_id for x in out} == {"a", "b", "c"} and len(out) == 4 and out[3].id == "a-1"


def test_order_by_doc_keeps_doc_rank() -> None:
    docs = [h("b-0", "b", 1), h("a-0", "a", 0.5)]
    passages = [h("a-0", "a", 0.5), h("b-1", "b", 1), h("b-0", "b", 1)]
    assert [x.doc_id for x in order_by_doc(passages, docs)] == ["b", "b", "a"]


def test_retrieve_with_chunks_per_doc_keeps_selected_docs(services, monkeypatch) -> None:
    from rag.schemas import RagConfig

    cfg = RagConfig(index="base", search="dense", top_k=5)
    monkeypatch.setattr(services.settings, "group_by_doc", True)
    monkeypatch.setattr(services.settings, "chunks_per_doc", 1)
    one = services.retriever.retrieve("scaffolder template", cfg, 5)
    monkeypatch.setattr(services.settings, "chunks_per_doc", 3)
    three = services.retriever.retrieve("scaffolder template", cfg, 5)
    seen = list(dict.fromkeys(x.doc_id for x in three.hits))
    assert seen == list(dict.fromkeys(x.doc_id for x in one.hits))  # mesmos docs, mesma ordem
    assert len(three.hits) >= len(one.hits)
