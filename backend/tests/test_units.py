"""Testes das funções puras: limpeza, citações, RRF, diversidade e merge."""
from __future__ import annotations

from rag.guardrails import CitationStreamFilter, filter_triage_labels, strip_invalid_citations
from rag.retrieval import Hit, cap_context, diversify, merge_neighbors, rrf_fuse
from rag.text import clean_issue_body


def hit(cid: str, doc: str, typ: str, score: float, idx: int = 0) -> Hit:
    return Hit(cid, doc, f"texto {cid}", {"type": typ, "doc_id": doc, "chunk_index": idx}, score, dense_score=score)


def test_clean_issue_body() -> None:
    body = "<!-- apague isto -->\n## Descrição\nfalha no scaffolder\n## Contexto\n\n- [ ] li a doc\n- [x] procurei\n```\n" + \
        "\n".join(f"linha {i}" for i in range(40)) + "\n```"
    out = clean_issue_body(body)
    assert "apague" not in out and "[ ] li a doc" not in out and "[x] procurei" in out
    assert "## Descrição" in out and "## Contexto" in out  # Contexto tem conteúdo (checkbox marcado)
    assert "linha 14" in out and "linha 15" not in out and "log cortado" in out


def test_clean_issue_body_drops_empty_heading() -> None:
    assert clean_issue_body("### Logs\n\n### Versão\n1.2") == "### Versão\n1.2"


def test_strip_invalid_citations() -> None:
    text, removed = strip_invalid_citations("A [1] B [3] C [12].", k=2)
    assert text == "A [1] B C." and removed == [3, 12]


def test_stream_filter_across_chunks() -> None:
    filt = CitationStreamFilter(k=2)
    pieces = ["Isso ", "[", "1", "] e ", "aquilo [", "9", "]", " fim [2"]
    out = "".join(filt.feed(p) for p in pieces) + filt.flush()
    assert out == "Isso [1] e aquilo fim [2"
    assert filt.removed == [9]


def test_rrf_fuse() -> None:
    fused = rrf_fuse([[("a", 0.9), ("b", 0.8)], [("b", 10.0), ("c", 5.0)]], k=60)
    assert fused[0][0] == "b"
    assert abs(fused[0][1] - (1 / 62 + 1 / 61)) < 1e-9


def test_diversify_limits_per_doc_and_keeps_doc_group() -> None:
    cands = [hit(f"i1-{i}", "issue-1", "issue", 0.9 - i * 0.01, i) for i in range(5)]
    cands += [hit("i2-0", "issue-2", "issue", 0.8), hit("d1-0", "doc-1", "doc", 0.5)]
    out = diversify(cands, top_k=4, is_reasonable=lambda r, h: h.score >= 0.35)
    assert sum(h.doc_id == "issue-1" for h in out) <= 3
    assert any(h.doc_id == "doc-1" for h in out) and len(out) == 4


def test_merge_neighbors_and_cap() -> None:
    hits = [hit("d-000", "d", "doc", 0.9, 0), hit("d-001", "d", "doc", 0.7, 1), hit("d-005", "d", "doc", 0.6, 5)]
    merged = merge_neighbors(hits)
    assert [m.chunk_ids for m in merged] == [["d-000", "d-001"], ["d-005"]]
    assert merged[0].score == 0.9
    long = [Hit("x", "x", "a" * 4000, {}, 1.0), Hit("y", "y", "b" * 40000, {}, 0.5)]
    capped = cap_context(long, max_tokens=6000)
    assert sum(len(h.text) for h in capped) <= 6000 * 4 + 10


def test_filter_triage_labels() -> None:
    names = [lb["name"] for lb in filter_triage_labels(
        [{"name": n} for n in ["type:bug", "needs:repro", "needs:triage", "domain:web", "stale", "needs:more-info"]])]
    assert names == ["type:bug", "needs:repro", "domain:web", "needs:more-info"]
