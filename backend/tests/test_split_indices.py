"""Split issues/docs ligado por padrão só nos índices de RETRIEVAL_SPLIT_TYPES_INDICES (padrão: logico)."""
from __future__ import annotations

from dataclasses import replace

from rag.retrieval import default_split_types
from rag.schemas import RagConfig

Q = "scaffolder template github"


def ids(res):
    return [h.id for h in res.hits]


def test_settings_split_indices_default_and_env(monkeypatch) -> None:
    from rag.settings import load_settings

    s = load_settings()
    assert s.split_types is False and s.split_types_indices == ("logico",)
    monkeypatch.setenv("RETRIEVAL_SPLIT_TYPES_INDICES", " base, LOGICO ,")
    assert load_settings().split_types_indices == ("base", "logico")
    monkeypatch.setenv("RETRIEVAL_SPLIT_TYPES_INDICES", "")
    assert load_settings().split_types_indices == ()


def test_default_split_types_rules(settings) -> None:
    s = replace(settings, split_types=False, split_types_indices=("logico",))
    assert default_split_types(s, "logico") and default_split_types(s, "Logico")
    assert not default_split_types(s, "base") and not default_split_types(s, None)
    assert not default_split_types(replace(s, split_types_indices=()), "logico")
    assert default_split_types(replace(s, split_types=True, split_types_indices=()), "base")  # global liga tudo


def test_base_unchanged_logico_split_by_default(services) -> None:
    r = services.retriever
    assert r.settings.split_types is False and "logico" in r.settings.split_types_indices
    # base: padrão == split desligado (comportamento idêntico ao de antes)
    for search in ("dense",):
        base_def = r.retrieve(Q, RagConfig(index="base", search=search, top_k=4), 4)
        base_off = r.retrieve(Q, RagConfig(index="base", search=search, top_k=4, split_types=False), 4)
        assert ids(base_def) == ids(base_off)
    # logico: padrão == split ligado; a requisição ainda pode desligar
    lg_def = r.retrieve(Q, RagConfig(index="logico", search="dense", top_k=4), 4)
    lg_on = r.retrieve(Q, RagConfig(index="logico", search="dense", top_k=4, split_types=True), 4)
    lg_off = r.retrieve(Q, RagConfig(index="logico", search="dense", top_k=4, split_types=False), 4)
    assert ids(lg_def) == ids(lg_on)
    assert lg_off.hits


def test_request_override_beats_index_default(services) -> None:
    r = services.retriever
    on_base = r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4, split_types=True), 4)
    off_base = r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4, split_types=False), 4)
    r.settings = replace(r.settings, split_types_indices=("base",))
    assert ids(r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4), 4)) == ids(on_base)
    assert ids(r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4, split_types=False), 4)) == ids(off_base)


def test_split_path_taken_only_where_expected(services, monkeypatch) -> None:
    import rag.retrieval as rt

    calls: list[str] = []
    real = rt.split_by_type

    def spy(*a, **k):
        calls.append("split")
        return real(*a, **k)

    monkeypatch.setattr(rt, "split_by_type", spy)
    r = services.retriever
    r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4), 4)
    assert calls == []                                   # base: sem split por padrão
    r.retrieve(Q, RagConfig(index="logico", search="dense", top_k=4), 4)
    assert calls == ["split"]                            # logico: split por padrão
    r.retrieve(Q, RagConfig(index="logico", search="dense", top_k=4, split_types=False), 4)
    assert calls == ["split"]                            # requisição desliga
    r.retrieve(Q, RagConfig(index="base", search="dense", top_k=4, split_types=True), 4)
    assert calls == ["split", "split"]                   # requisição liga no base
