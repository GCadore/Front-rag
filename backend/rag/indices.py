"""Carregamento dos índices em DATA_DIR e dos modelos (seção 6 da spec).

Estrutura esperada:
  data_full/chunks/chunks.jsonl            chunks do base
  data_full/index/{chroma,bm25,embeddings.npy,ids.json}
  data_full/index_lean/{chroma,chunks.jsonl,embeddings.npy,ids.json}   (bm25 é construído aqui)
  data_full/index_logico/...               mesma estrutura do index_lean, coleção "backstage_chunks_logico"
  data_full/addons/{changelog,commit,review}/{chunks.jsonl,embeddings.npy,ids.json}

Imports pesados (numpy, chromadb, bm25s, sentence_transformers) ficam dentro
das funções para que os testes rodem sem eles.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .retrieval import Retriever
from .settings import Settings
from .text import BM25Tokenizer

log = logging.getLogger("rag.indices")

INDEX_DIRS = {"base": "index", "enxuto": "index_lean", "logico": "index_logico"}
ADDONS = ("changelog", "commit", "review")


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


# --------------------------------------------------------------------------- #
# Buscadores
# --------------------------------------------------------------------------- #
class NumpyDense:
    """Busca densa exata: vetores normalizados, então score = produto escalar."""

    def __init__(self, ids: list[str], matrix: Any):
        import numpy as np

        if len(ids) != len(matrix):
            raise ValueError(f"ids ({len(ids)}) e embeddings ({len(matrix)}) com tamanhos diferentes")
        self.ids = ids
        self.matrix = np.asarray(matrix, dtype=np.float32)

    def search(self, vector: Any, n: int) -> list[tuple[str, float]]:
        import numpy as np

        scores = self.matrix @ np.asarray(vector, dtype=np.float32)
        n = min(n, len(self.ids))
        if n <= 0:
            return []
        top = np.argpartition(-scores, n - 1)[:n]
        top = top[np.argsort(-scores[top])]
        return [(self.ids[i], float(scores[i])) for i in top]


class ChromaDense:
    """Coleção Chroma com métrica cosseno: score = 1 - distância."""

    def __init__(self, collection: Any, store: dict[str, Chunk]):
        self.collection = collection
        self.store = store

    def search(self, vector: Any, n: int) -> list[tuple[str, float]]:
        res = self.collection.query(
            query_embeddings=[list(map(float, vector))],
            n_results=n,
            include=["distances", "documents", "metadatas"],
        )
        ids = res["ids"][0]
        dists = res["distances"][0]
        docs = (res.get("documents") or [[None] * len(ids)])[0]
        metas = (res.get("metadatas") or [[None] * len(ids)])[0]
        for cid, doc, meta in zip(ids, docs, metas):
            if cid not in self.store and doc is not None:  # completa o store se faltar
                self.store[cid] = Chunk(cid, doc, dict(meta or {}))
        return [(cid, 1.0 - float(d)) for cid, d in zip(ids, dists)]


class BM25Searcher:
    def __init__(self, model: Any, ids: list[str], tokenizer: BM25Tokenizer):
        self.model = model
        self.ids = ids
        self.tokenizer = tokenizer

    def search(self, query: str, n: int) -> list[tuple[str, float]]:
        tokens = self.tokenizer.query(query)
        if not tokens:
            return []
        try:
            docs, scores = self.model.retrieve([tokens], k=min(n, len(self.ids)), show_progress=False)
        except Exception:  # noqa: BLE001 - p.ex. nenhum token no vocabulário
            log.debug("BM25 sem resultado para %r", query, exc_info=True)
            return []
        return [(self.ids[int(d)], float(s)) for d, s in zip(docs[0], scores[0])]


@dataclass
class Index:
    name: str
    store: dict[str, Chunk]
    dense: Any                 # NumpyDense | ChromaDense
    bm25: BM25Searcher | None
    bm25_boost: BM25Searcher | None = None  # BM25 com título/labels reforçados (BM25_TITLE_BOOST/BM25_LABEL_BOOST)

    def has_chunk(self, cid: str) -> bool:
        return cid in self.store

    def chunk(self, cid: str) -> Chunk:
        return self.store[cid]


# --------------------------------------------------------------------------- #
# Leitura de arquivos
# --------------------------------------------------------------------------- #
def read_chunks(path: Path) -> dict[str, Chunk]:
    store: dict[str, Chunk] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            store[row["id"]] = Chunk(row["id"], row.get("text", ""), dict(row.get("metadata") or {}))
    return store


def read_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):  # aceita {"ids": [...]}
        data = data.get("ids", [])
    return [str(x) for x in data]


def _load_embeddings(directory: Path) -> tuple[list[str], Any] | None:
    emb, ids = directory / "embeddings.npy", directory / "ids.json"
    if not (emb.is_file() and ids.is_file()):
        return None
    import numpy as np

    return read_ids(ids), np.load(emb, mmap_mode="r")


def _open_chroma(directory: Path, name: str) -> Any | None:
    chroma_dir = directory / "chroma"
    if not chroma_dir.is_dir():
        return None
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        return client.get_collection(name)
    except Exception:  # noqa: BLE001
        cols = client.list_collections()
        if not cols:
            return None
        first = cols[0]
        log.warning("Coleção %r não existe em %s; usando %r", name, chroma_dir, getattr(first, "name", first))
        return client.get_collection(getattr(first, "name", first))


def _bm25_params(settings: Settings) -> dict[str, Any]:
    cfg = settings.bm25_config
    return {k: cfg[k] for k in ("k1", "b", "method", "delta") if k in cfg}


def build_bm25(texts: list[str], ids: list[str], tokenizer: BM25Tokenizer, settings: Settings) -> BM25Searcher:
    import bm25s

    model = bm25s.BM25(**_bm25_params(settings))
    model.index(tokenizer.corpus(texts), show_progress=False)
    return BM25Searcher(model, ids, tokenizer)


BOOST_TYPES = {"issue", "pr"}


def boosted_text(chunk: Chunk, title_boost: int, label_boost: int) -> str:
    """Texto do chunk para o BM25 reforçado: em issues/PRs, o título entra mais `title_boost` vezes
    e as labels (área, tipo, integração; "area:catalog" -> "area catalog") mais `label_boost` vezes.
    O cabeçalho do chunk já tem título e labels uma vez; docs/ADRs ficam iguais."""
    meta = chunk.metadata or {}
    if str(meta.get("type", "")) not in BOOST_TYPES:
        return chunk.text
    extra: list[str] = []
    title = str(meta.get("title") or "").strip()
    if title and title_boost > 0:
        extra += [title] * title_boost
    labels = [lb.strip() for lb in str(meta.get("labels") or "").split("|") if lb.strip()]
    labels = [lb.replace(":", " ") for lb in labels if lb.startswith(("area:", "type:", "integration:"))]
    if labels and label_boost > 0:
        extra += [" ".join(labels)] * label_boost
    return chunk.text if not extra else chunk.text + "\n" + "\n".join(extra)


def build_boosted_bm25(
    index: "Index", tokenizer: BM25Tokenizer, settings: Settings, title_boost: int, label_boost: int
) -> BM25Searcher | None:
    """Segundo BM25, em memória, com o mesmo corpus do BM25 normal do índice."""
    if index.bm25 is None or (title_boost <= 0 and label_boost <= 0):
        return None
    ids = [i for i in index.bm25.ids if i in index.store]
    return build_bm25([boosted_text(index.store[i], title_boost, label_boost) for i in ids], ids, tokenizer, settings)


def load_or_build_bm25(
    directory: Path, store: dict[str, Chunk], tokenizer: BM25Tokenizer, settings: Settings, build: bool
) -> BM25Searcher | None:
    bm25_dir = directory / "bm25"
    ids_path = bm25_dir / "bm25_ids.json"
    if not ids_path.is_file() and (directory / "bm25_ids.json").is_file():
        ids_path = directory / "bm25_ids.json"  # aceita o ids ao lado da pasta bm25/
    if bm25_dir.is_dir() and ids_path.is_file():
        import bm25s

        return BM25Searcher(bm25s.BM25.load(str(bm25_dir)), read_ids(ids_path), tokenizer)
    if not build or not store:
        return None
    # enxuto/logico: não há BM25 salvo -> constrói e salva para as próximas subidas
    log.info("Construindo BM25 de %s (%d chunks)", directory, len(store))
    ids = list(store)
    searcher = build_bm25([store[i].text for i in ids], ids, tokenizer, settings)
    bm25_dir.mkdir(parents=True, exist_ok=True)
    searcher.model.save(str(bm25_dir))
    ids_path.write_text(json.dumps(ids), encoding="utf-8")
    return searcher


def _dense_for(name: str, directory: Path, store: dict[str, Chunk], settings: Settings) -> Any | None:
    collection = _open_chroma(directory, settings.collection_for(name))
    if collection is not None:
        return ChromaDense(collection, store)
    emb = _load_embeddings(directory)
    return NumpyDense(*emb) if emb else None


def load_simple_index(name: str, settings: Settings, tokenizer: BM25Tokenizer) -> Index | None:
    directory = settings.data_dir / INDEX_DIRS[name]
    if not directory.is_dir():
        return None
    chunks_path = settings.data_dir / "chunks" / "chunks.jsonl" if name == "base" else directory / "chunks.jsonl"
    store = read_chunks(chunks_path) if chunks_path.is_file() else {}
    dense = _dense_for(name, directory, store, settings)
    if dense is None:
        log.warning("Índice %s sem chroma/ nem embeddings.npy; ignorando", name)
        return None
    bm25 = load_or_build_bm25(directory, store, tokenizer, settings, build=name != "base")
    return Index(name, store, dense, bm25)


def load_base_extras(settings: Settings, tokenizer: BM25Tokenizer) -> Index | None:
    """Base + addons: busca densa exata em numpy e BM25 em memória."""
    import numpy as np

    base_dir = settings.data_dir / INDEX_DIRS["base"]
    base_chunks = settings.data_dir / "chunks" / "chunks.jsonl"
    base_emb = _load_embeddings(base_dir)
    if base_emb is None or not base_chunks.is_file():
        return None
    store = read_chunks(base_chunks)
    all_ids, mats = list(base_emb[0]), [np.asarray(base_emb[1], dtype=np.float32)]
    found_addon = False
    for addon in ADDONS:
        addon_dir = settings.data_dir / "addons" / addon
        emb = _load_embeddings(addon_dir)
        if emb is None or not (addon_dir / "chunks.jsonl").is_file():
            continue
        store.update(read_chunks(addon_dir / "chunks.jsonl"))
        all_ids.extend(emb[0])
        mats.append(np.asarray(emb[1], dtype=np.float32))
        found_addon = True
    if not found_addon:
        return None
    dense = NumpyDense(all_ids, np.concatenate(mats, axis=0))
    bm25_ids = [i for i in all_ids if i in store]
    bm25 = build_bm25([store[i].text for i in bm25_ids], bm25_ids, tokenizer, settings)
    return Index("base_extras", store, dense, bm25)


def load_indices(settings: Settings, tokenizer: BM25Tokenizer) -> dict[str, Index]:
    indices: dict[str, Index] = {}
    loaders = {
        "base": lambda: load_simple_index("base", settings, tokenizer),
        "enxuto": lambda: load_simple_index("enxuto", settings, tokenizer),
        "logico": lambda: load_simple_index("logico", settings, tokenizer),
        "base_extras": lambda: load_base_extras(settings, tokenizer),
    }
    for name, loader in loaders.items():
        try:
            index = loader()
        except Exception:  # noqa: BLE001 - um índice quebrado não derruba a API
            log.exception("Falha ao carregar o índice %s", name)
            continue
        if index is not None:
            tb = int(getattr(settings, "bm25_title_boost", 0) or 0)
            lb = int(getattr(settings, "bm25_label_boost", 0) or 0)
            if tb > 0 or lb > 0:
                try:
                    index.bm25_boost = build_boosted_bm25(index, tokenizer, settings, tb, lb)
                except Exception:  # noqa: BLE001 - sem o reforço, segue o BM25 normal
                    log.exception("Falha ao montar o BM25 reforçado de %s", name)
            indices[name] = index
            log.info(
                "Índice %s carregado (%d chunks, bm25=%s, bm25_reforcado=%s)",
                name, len(index.store), index.bm25 is not None, index.bm25_boost is not None,
            )
    return indices


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, device=device)
        if device.startswith("cuda"):
            self.model.half()  # fp16 na GPU

    def encode(self, texts: list[str]) -> Any:
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)


class CrossEncoderReranker:
    """bge-reranker-v2-m3. Devolve logits (sem sigmoid): MIN_SCORE_RERANK=0.0 por padrão."""

    def __init__(self, model_name: str, device: str):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name, device=device, max_length=512)
        if device.startswith("cuda"):
            try:
                self.model.model.half()
            except Exception:  # noqa: BLE001
                log.warning("Não deu para usar fp16 no reranker")

    def score(self, query: str, texts: list[str]) -> list[float]:
        import torch

        pairs = [(query, t) for t in texts]
        identity = torch.nn.Identity()
        # O nome do argumento mudou entre versões do sentence-transformers
        for kwargs in ({"activation_fn": identity}, {"activation_fct": identity}):
            try:
                return [float(s) for s in self.model.predict(pairs, batch_size=16, show_progress_bar=False, **kwargs)]
            except TypeError:
                continue
        return [float(s) for s in self.model.predict(pairs, batch_size=16, show_progress_bar=False)]


def script_search_paths(settings: Settings) -> list[Path]:
    """Onde procurar os scripts do time (05b_bm25_index.py, query_demo.py)."""
    return [Path.cwd(), settings.data_dir.parent, settings.data_dir]


def build_retriever(settings: Settings, search_paths: Iterable[Path] | None = None) -> Retriever | None:
    """Carrega índices e modelos uma vez (chamado no lifespan)."""
    if not settings.data_dir.is_dir():
        log.warning("DATA_DIR=%s não existe; API sobe sem índices", settings.data_dir)
        return None
    tokenizer = BM25Tokenizer(settings.bm25_config, search_paths or script_search_paths(settings))
    indices = load_indices(settings, tokenizer)
    if not indices:
        log.warning("Nenhum índice encontrado em %s", settings.data_dir)
        return None
    embedder = SentenceTransformerEmbedder(settings.embed_model, settings.embed_device)
    reranker = None
    if settings.enable_reranker:
        try:
            reranker = CrossEncoderReranker(settings.rerank_model, settings.embed_device)
        except Exception:  # noqa: BLE001
            log.exception("Reranker não carregou; seguindo sem")
    return Retriever(settings, indices, embedder, reranker)
