# Exemplo de endpoint de retrieval pra colar no modal_app.py.
# Recebe {"query", "k", "index", "search", "rerank"} e devolve {"chunks": [{"text", "source", "url", "score"}]}.
#   index:  "base" | "enxuto" | "base_extras"  -> uma coleção do Chroma por índice
#   search: "dense" | "bm25" | "hybrid"        -> híbrida junta as duas com RRF
#   rerank: true | false                       -> reordena com o bge-reranker
# Ajuste CHROMA_PATH, COLLECTIONS e as chaves de metadado pro que vocês usaram na indexação.

import math

import modal

app = modal.App("backstage-rag")
volume = modal.Volume.from_name("backstage-rag-data")

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "chromadb", "sentence-transformers", "rank_bm25", "fastapi[standard]"
)

CHROMA_PATH = "/data/chroma"
COLLECTIONS = {
    "base": "backstage_base",
    "enxuto": "backstage_enxuto",
    "base_extras": "backstage_base_extras",
}
CANDIDATES = 30  # quantos trechos cada busca traz antes de cortar em k


def tokenize(text: str) -> list[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 1]


@app.cls(image=image, gpu="T4", volumes={"/data": volume}, scaledown_window=300)
class Retriever:
    @modal.enter()
    def load(self):
        import chromadb
        from rank_bm25 import BM25Okapi
        from sentence_transformers import CrossEncoder, SentenceTransformer

        self.embedder = SentenceTransformer("BAAI/bge-m3")
        self.reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
        client = chromadb.PersistentClient(path=CHROMA_PATH)

        # Pra cada índice: a coleção do Chroma e um BM25 em memória com os mesmos documentos
        self.indexes = {}
        for key, name in COLLECTIONS.items():
            try:
                col = client.get_collection(name)
            except Exception:
                continue
            data = col.get(include=["documents", "metadatas"])
            self.indexes[key] = {
                "col": col,
                "ids": data["ids"],
                "docs": data["documents"],
                "metas": data["metadatas"],
                "bm25": BM25Okapi([tokenize(d) for d in data["documents"]]),
            }

    def dense(self, idx, query: str) -> list[tuple[int, float]]:
        emb = self.embedder.encode([query], normalize_embeddings=True).tolist()
        res = idx["col"].query(query_embeddings=emb, n_results=CANDIDATES)
        pos = {doc_id: i for i, doc_id in enumerate(idx["ids"])}
        return [(pos[d], 1 - dist) for d, dist in zip(res["ids"][0], res["distances"][0])]

    def bm25(self, idx, query: str) -> list[tuple[int, float]]:
        scores = idx["bm25"].get_scores(tokenize(query))
        top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:CANDIDATES]
        best = max(scores[top[0]], 1e-9) if top else 1
        # Normaliza pra 0..1 pra ficar comparável com o dense no front
        return [(i, float(scores[i] / best)) for i in top if scores[i] > 0]

    @staticmethod
    def rrf(*rankings: list[tuple[int, float]], k: int = 60) -> list[tuple[int, float]]:
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, (i, _) in enumerate(ranking):
                fused[i] = fused.get(i, 0) + 1 / (k + rank + 1)
        best = max(fused.values(), default=1)
        return sorted(((i, s / best) for i, s in fused.items()), key=lambda x: x[1], reverse=True)

    @modal.fastapi_endpoint(method="POST", label="backstage-rag-retrieve")
    def retrieve(self, body: dict):
        query = body["query"]
        k = int(body.get("k", 5))
        idx = self.indexes.get(body.get("index", "base")) or self.indexes["base"]
        search = body.get("search", "hybrid")

        if search == "dense":
            ranked = self.dense(idx, query)
        elif search == "bm25":
            ranked = self.bm25(idx, query)
        else:
            ranked = self.rrf(self.dense(idx, query), self.bm25(idx, query))

        if body.get("rerank"):
            cand = ranked[:CANDIDATES]
            logits = self.reranker.predict([(query, idx["docs"][i]) for i, _ in cand])
            ranked = sorted(
                ((i, 1 / (1 + math.exp(-float(l)))) for (i, _), l in zip(cand, logits)),
                key=lambda x: x[1],
                reverse=True,
            )

        chunks = []
        for i, score in ranked[:k]:
            meta = idx["metas"][i] or {}
            chunks.append({
                "text": idx["docs"][i],
                "source": meta.get("source"),
                "url": meta.get("url"),
                "score": round(float(score), 4),
            })
        return {"chunks": chunks}
