"""Testes das tarefas: tokenizer do BM25, troca de índice, guardrails on/off,
formato das citações, /health, MIN_SCORE configurável e erro 503 do LLM."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rag.guardrails import REFUSAL_TEXT, passes_min_score
from rag.retrieval import RetrievalResult
from rag.settings import Settings, _min_scores, default_data_dir

RAG_CFG = {"rag": True, "index": "base", "search": "dense", "reranker": False, "guardrails": True, "top_k": 8}


def chat(client: TestClient, question: str, **cfg) -> dict:
    resp = client.post("/chat", json={"messages": [{"role": "user", "content": question}],
                                      "config": {**RAG_CFG, **cfg}, "stream": False})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------- 1. tokenizer do BM25 ------------------------- #
CORPUS = [
    "The scaffolder runs templates and the runners were running actions",
    "Catalog processing of entities and locations",
    "TechDocs builds documentation with mkdocs",
]


def test_query_tokens_match_index_vocabulary() -> None:
    bm25s = pytest.importorskip("bm25s")
    pytest.importorskip("Stemmer")
    from rag.text import BM25Tokenizer

    tok = BM25Tokenizer({"stemmer": "english", "stopwords": "en"})
    model = bm25s.BM25()
    model.index(tok.corpus(CORPUS), show_progress=False)

    tokens = tok.query("Running the templates in the Scaffolder")
    assert tokens == ["run", "templat", "scaffold"]           # stem "english", sem stopwords
    assert all(t in model.vocab_dict for t in tokens)          # batem com o vocabulário do índice
    docs, _ = model.retrieve([tokens], k=1, show_progress=False)
    assert int(docs[0][0]) == 0


def test_stopwords_come_from_config() -> None:
    pytest.importorskip("bm25s")
    pytest.importorskip("Stemmer")
    from rag.text import BM25Tokenizer

    tok = BM25Tokenizer({"stemmer": "english", "stopwords": ["scaffolder", "the"]})
    assert tok.query("the scaffolder templates") == ["templat"]


def test_team_get_stemmer_is_used_when_present(tmp_path: Path) -> None:
    pytest.importorskip("Stemmer")
    from rag.text import load_stemmer

    (tmp_path / "05b_bm25_index.py").write_text(
        "import Stemmer\n"
        "class TeamStemmer(Stemmer.Stemmer):\n"
        "    lang_pedida = None\n"
        "def get_stemmer(lang):\n"
        "    s = TeamStemmer(lang)\n"
        "    s.lang_pedida = lang\n"
        "    return s\n",
        encoding="utf-8",
    )
    stemmer = load_stemmer({}, [tmp_path])
    assert type(stemmer).__name__ == "TeamStemmer"      # veio do script do time
    assert stemmer.lang_pedida == "english"              # chamado com get_stemmer("english")
    assert stemmer.stemWord("running") == "run"


# --------------------------- 2. troca de índice --------------------------- #
def test_switching_index_changes_sources(client: TestClient) -> None:
    base = chat(client, "Scaffolder template erro", index="base")
    logico = chat(client, "Scaffolder template erro", index="logico")
    base_ids = {s["doc_id"] for s in base["sources"]}
    logico_ids = {s["doc_id"] for s in logico["sources"]}
    assert logico_ids and logico_ids <= {"adr-012", "issue-777"}
    assert not base_ids & logico_ids
    assert logico["config"]["index"] == "logico"


def test_collection_names_per_index() -> None:
    settings = Settings(config={"embed": {"chroma_collection": "backstage_chunks"}})
    assert settings.collection_for("base") == "backstage_chunks"
    assert settings.collection_for("logico") == "backstage_chunks_logico"


def test_data_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATA_DIR", "RAG_DATA_DIR", "MODAL_TASK_ID", "MODAL_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    assert default_data_dir() == Path("data_full")              # local
    monkeypatch.setenv("MODAL_TASK_ID", "ta-123")
    assert default_data_dir() == Path("/data")                   # no Modal
    monkeypatch.setenv("DATA_DIR", "/mnt/rag")
    assert default_data_dir() == Path("/mnt/rag")                # env manda


def test_logico_index_loads_from_its_folder(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    from rag.indices import load_simple_index

    folder = tmp_path / "index_logico"
    folder.mkdir()
    rows = [{"id": "adr-1-000", "text": "ADR um", "metadata": {"type": "adr", "doc_id": "adr-1"}}]
    (folder / "chunks.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    np.save(folder / "embeddings.npy", np.ones((1, 4), dtype=np.float32) / 2)
    (folder / "ids.json").write_text(json.dumps(["adr-1-000"]), encoding="utf-8")

    class NoBM25Tokenizer:  # BM25 não é o foco aqui
        pass

    import rag.indices as indices

    orig = indices.load_or_build_bm25
    indices.load_or_build_bm25 = lambda *a, **k: None
    try:
        index = load_simple_index("logico", Settings(data_dir=tmp_path), NoBM25Tokenizer())  # type: ignore[arg-type]
    finally:
        indices.load_or_build_bm25 = orig
    assert index is not None and index.name == "logico" and "adr-1-000" in index.store


# --------------------------- 3. guardrails on/off ------------------------- #
INVENTED_TRIAGE = json.dumps({
    "labels": [{"name": "area:scaffolder", "confidence": "alta"}, {"name": "bug-critico", "confidence": "baixa"}],
    "related": [{"n": 1, "reason": "mesmo erro"}, {"n": 42, "reason": "inventado"}],
    "docs": [{"n": 77}],
    "explanation": "Mesmo erro [1][55] e da #99999.",
})


def test_triage_guardrails_on_validates_everything(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [INVENTED_TRIAGE]
    data = client.post("/triage", json={"title": "Scaffolder fails with GitHub app auth", "config": RAG_CFG}).json()
    assert [lb["name"] for lb in data["labels"]] == ["area:scaffolder"]
    assert data["removed"]["labels"] == ["bug-critico"]
    assert data["removed"]["related"] == ["[42]"] and data["removed"]["docs"] == ["[77]"]
    assert data["removed"]["citations"] == [55] and data["removed"]["mentions"] == ["#99999"]


def test_triage_guardrails_off_validates_nothing(client: TestClient, fake_llm) -> None:
    fake_llm.json_replies = [INVENTED_TRIAGE]
    data = client.post("/triage", json={"title": "Scaffolder fails with GitHub app auth",
                                        "config": {**RAG_CFG, "guardrails": False}}).json()
    assert [lb["name"] for lb in data["labels"]] == ["area:scaffolder", "bug-critico"]
    assert sorted(r["n"] for r in data["related"]) == [1, 42]
    assert [d["n"] for d in data["docs"]] == [77]
    assert data["explanation"] == "Mesmo erro [1][55] e da #99999."
    assert all(v == [] for v in data["removed"].values())


def test_chat_guardrails_off_skips_gate_and_citation_check(client: TestClient, fake_llm) -> None:
    on = chat(client, "receita de bolo")
    assert on["refused"] is True and on["answer"] == REFUSAL_TEXT and fake_llm.calls == []

    off = chat(client, "receita de bolo", guardrails=False)
    assert off["refused"] is False and len(fake_llm.calls) == 1   # sem corte de score
    assert "[9]" in off["answer"] and off["removed_citations"] == []
    system = fake_llm.calls[-1]["messages"][0]["content"]
    assert "SOMENTE" not in system                                 # prompt não-estrito


# --------------------------- 4. MIN_SCORE --------------------------------- #
def test_min_score_reads_env_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DENSE", "BM25", "RERANK"):
        monkeypatch.delenv(f"MIN_SCORE_{key}", raising=False)
    config = {"guardrails": {"min_score": {"dense": 0.4, "rerank": -1.5}}}
    assert _min_scores(config) == {"dense": 0.4, "bm25": None, "rerank": -1.5}
    monkeypatch.setenv("MIN_SCORE_DENSE", "0.55")
    assert _min_scores(config)["dense"] == 0.55


def test_gate_without_threshold_only_refuses_empty_results() -> None:
    from rag.retrieval import Hit

    hit = Hit("a", "a", "texto", {}, score=-3.0)
    weak = RetrievalResult(hits=[hit], scorer="rerank", relevance=-3.0)  # logit negativo
    assert passes_min_score(weak, {"rerank": None}) is True
    assert passes_min_score(weak, {"rerank": 0.0}) is False
    assert passes_min_score(RetrievalResult(hits=[], scorer="dense", relevance=0.9), {"dense": None}) is False


def test_log_has_top_scores_for_calibration(client: TestClient, settings) -> None:
    chat(client, "Como funciona o Scaffolder?")
    record = json.loads(settings.log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["top_scores"]["dense"] > 0
    assert record["min_score"] == {"scorer": "dense", "threshold": 0.2, "applied": True}


# --------------------------- 5. formato das citações ---------------------- #
def test_citation_format(client: TestClient) -> None:
    data = chat(client, "Scaffolder fails with GitHub App auth")
    for src in data["sources"]:
        assert {"n", "source", "number", "title", "url"} <= src.keys()
    issue = next(s for s in data["sources"] if s["doc_id"] == "issue-21034")
    assert issue["source"] == "issue #21034" and issue["number"] == 21034
    assert issue["title"] == "Scaffolder fails with GitHub App auth"
    assert issue["url"] == "https://github.com/backstage/backstage/issues/21034"
    doc = next(s for s in data["sources"] if s["doc_id"] == "doc-scaffolder")
    assert doc["source"] == "doc-scaffolder" and doc["number"] is None


# --------------------------- 6. /health ----------------------------------- #
def test_health_reports_loaded_indices(client: TestClient) -> None:
    data = client.get("/health").json()
    assert data["indices"] == ["base", "logico"] and data["status"] == "ok"


# --------------------------- 7. LLM indisponível -------------------------- #
def test_compare_reports_llm_unavailable_per_config(client: TestClient, fake_llm) -> None:
    fake_llm.fail = True
    results = client.post("/compare", json={"mode": "chat", "title": "Scaffolder", "configs": [RAG_CFG]}).json()["results"]
    assert results[0]["error"] == "llm_unavailable" and results[0]["retry"] is True and results[0]["status"] == 503


# --------------------------- timeout do LLM ------------------------------- #
def test_llm_timeout_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag.settings import load_settings

    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    assert load_settings().llm_timeout_s == 120.0
    monkeypatch.setenv("LLM_TIMEOUT_S", "300")
    assert load_settings().llm_timeout_s == 300.0


def test_api_passes_env_timeout_to_llm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("openai")
    import api
    import rag.indices

    monkeypatch.setenv("LLM_TIMEOUT_S", "300")
    monkeypatch.setattr(rag.indices, "build_retriever", lambda settings: None)
    services = api.build_services()
    assert services.llm.timeout_s == 300.0
    assert services.llm.client.timeout == 300.0


# --------------------------- relacionados sem duplicata -------------------- #
def test_triage_related_and_docs_deduplicated_by_doc_id() -> None:
    from rag.guardrails import guard_triage
    from rag.retrieval import Hit
    from rag.schemas import TriageLLMOutput

    def hit(cid: str, doc_id: str, kind: str, idx: int, number: int | None = None) -> Hit:
        meta = {"type": kind, "doc_id": doc_id, "chunk_index": idx, "title": doc_id, "url": f"https://x/{doc_id}"}
        if number is not None:
            meta["number"] = number
        return Hit(cid, doc_id, "texto", meta, score=0.5)

    # [1] e [3] são trechos não vizinhos da mesma issue; [4] e [5], da mesma doc
    hits = [
        hit("issue-28190-000", "issue-28190", "issue", 0, 28190),
        hit("issue-20753-000", "issue-20753", "issue", 0, 20753),
        hit("issue-28190-003", "issue-28190", "issue", 3, 28190),
        hit("doc-techdocs-000", "doc-techdocs", "doc", 0),
        hit("doc-techdocs-004", "doc-techdocs", "doc", 4),
    ]
    output = TriageLLMOutput.model_validate({
        "related": [{"n": 1, "reason": "mesma causa"}, {"n": 3, "reason": "repetido"}, {"n": 2, "reason": "parecido"},
                    {"id": "issue-28190", "reason": "pelo doc_id"}],
        "docs": [{"n": 4}, {"n": 5}, {"n": 4}],
    })
    for enabled in (True, False):
        res = guard_triage(output, hits, allowed_labels=set(), enabled=enabled)
        assert [r["doc_id"] for r in res.related] == ["issue-28190", "issue-20753"]
        assert res.related[0]["reason"] == "mesma causa"          # fica o primeiro citado
        assert [d["doc_id"] for d in res.docs] == ["doc-techdocs"]
        assert res.removed["related"] == [] and res.removed["docs"] == []  # duplicata não é "inventada"
