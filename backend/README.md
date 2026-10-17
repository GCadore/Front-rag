# Backstage RAG API (backend)

API FastAPI que liga o front em Next ao RAG (Chroma + BM25) e ao LLM (Qwen). A especificação é o `API_SPEC.md`.

## Estrutura
```
api.py              app FastAPI: lifespan, auth (x-api-key), CORS, rotas
modal_app.py        exemplo de deploy no Modal
rag/settings.py     .env + config.yaml
rag/text.py         tokenizer/stemmer do BM25 e limpeza do corpo da issue
rag/indices.py      carrega base / enxuto / logico / base_extras e os modelos
rag/retrieval.py    dense, bm25, hybrid (RRF), reranker, diversidade, merge, limite de contexto
rag/llm.py          cliente OpenAI-compatível (Ollama, vLLM), timeout de 120 s
rag/guardrails.py   MIN_SCORE, limite de entrada, citações [n], menções #123/URLs, validação da triagem
rag/prompts.py      prompts de sistema (podem ser sobrescritos em prompts/*.txt)
rag/pipeline.py     fluxos de /chat, /triage e /compare
tests/              pytest com retriever e LLM falsos
```

## Rodar local (Ollama)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # ajuste DATA_DIR, RAG_API_KEY e os MIN_SCORE_*
ollama pull qwen2.5:7b
uvicorn api:app --port 8000 --reload
```
`DATA_DIR` aponta para a raiz dos dados (estrutura na seção 3 da spec). Padrão: `/data` no Modal e `./data_full` local; `RAG_DATA_DIR` ainda é aceito. Índices ausentes são pulados e o `/health` lista só os carregados.

| Índice | Pasta | Coleção Chroma | BM25 |
|---|---|---|---|
| `base` | `index/` | `backstage_chunks` (`embed.chroma_collection`) | salvo em `index/bm25/` |
| `enxuto` | `index_lean/` | a mesma do base | construído na 1ª subida e salvo em `index_lean/bm25/` |
| `logico` | `index_logico/` | `backstage_chunks_logico` (`embed.chroma_collection_logico`) | próprio, construído e salvo em `index_logico/bm25/` |
| `base_extras` | `index/` + `addons/*` | — (numpy) | em memória |

**Tokenizer do BM25:** a query passa pelo mesmo pré-processamento do índice: `bm25s.tokenize` com `get_stemmer("english")` e as stopwords de `bm25.stopwords` no config.yaml. Se o `05b_bm25_index.py` do time estiver no diretório atual ou ao lado de `data_full/`, o `get_stemmer` dele é usado; senão, o equivalente com PyStemmer.

**Ordem do retrieval:** busca (dense, BM25 ou híbrida com RRF usando `retrieval.rrf_k`) → reranker → diversidade por fonte → `top_k`.

## Variáveis de ambiente
As de `.env.example` (seção 2 da spec), mais estas opcionais:

| Variável | Padrão | Uso |
|---|---|---|
| `RAG_CONFIG` | `config.yaml` ao lado de `data_full/`, dentro dele ou no cwd | caminho do config.yaml |
| `LABELS_PATH` | `RAG_DATA_DIR/../labels.json`, depois `data/labels.json` | labels do repositório |
| `LOG_DIR` | `logs` | onde fica `requests.jsonl` |
| `PROMPTS_DIR` | `backend/prompts` | prompts `.txt` que sobrescrevem os padrões |
| `LLM_TIMEOUT_S` | `120` (300 no `modal_app.py`) | quanto a API espera o LLM; com 300, a 1ª pergunta espera a partida a frio do vLLM em vez de voltar erro |
| `DATA_DIR` | `/data` no Modal, `./data_full` local | raiz dos índices |
| `MIN_SCORE_DENSE` / `MIN_SCORE_BM25` / `MIN_SCORE_RERANK` | sem valor | limiares do gate; têm prioridade sobre `guardrails.min_score.*` do config.yaml |

**MIN_SCORE não tem valor fixo no código.** Sem limiar configurado, o gate só recusa quando a busca vem vazia (a API avisa no log ao subir). Cada escala é diferente: dense é cosseno (0..1), BM25 é score bruto e o do **reranker é logit** (pode ser negativo). Pra calibrar, cada linha de `logs/requests.jsonl` traz `top_scores` (melhor score de `dense`, `bm25`, `rrf` e `rerank`) e o limiar aplicado em `min_score`.

Chaves lidas do `config.yaml`: `embed.chroma_collection`, `embed.model`, `rerank.model`, `retrieval.rrf_k`, `retrieval.max_context_tokens`, `bm25.{stopwords,stemmer,k1,b,method}` (ou `retrieval.bm25.*`), `guardrails.min_score.{dense,rerank,bm25}` e `prompts.<nome>`.

## Endpoints
- `GET /health` (sem chave), `GET /labels`, `POST /chat` (`stream: true` devolve SSE com os eventos `sources`, `token`, `done` e `error`), `POST /triage`, `POST /compare` (até 4 configs, `mode` chat|triage).
- Todas, menos `/health`, exigem o header `x-api-key: $RAG_API_KEY`.
- Cada requisição vira uma linha em `logs/requests.jsonl` (config, ids, top scores, timings, o que os guardrails removeram).
- Cada trecho em `sources` traz `n`, `source` ("issue #119", "pr #600" ou o `doc_id`), `number`, `title`, `url`, `type`, `snippet` e `score`.
- **LLM frio ou fora do ar:** HTTP 503 com `{"error": "llm_unavailable", "retry": true, "message": ...}` e header `Retry-After`. No SSE, sai um evento `error` com o mesmo corpo antes de fechar. No `/compare`, só a configuração afetada volta assim.

## Guardrails: o que muda com `guardrails`
| | `true` | `false` |
|---|---|---|
| Gate MIN_SCORE (recusa sem chamar o LLM) | sim | não |
| Prompt | estrito (seção 7) | simples |
| Remove citações `[n]` inválidas | sim | não |
| Remove `#123`, links de issue/PR e URLs que não estão nos trechos nem na pergunta | sim (no stream: só reporta em `done.removed_mentions`) | não |
| Labels fora de `/labels`, `related` e `docs` fora dos trechos (triagem) | removidos | mantidos como o modelo gerou |

Com `guardrails=false` tudo desliga: é o modo "modelo cru" da comparação.

## Modal
```bash
cd backend
modal volume create backstage-rag-data
modal volume put backstage-rag-data ../data_full /data_full
modal secret create backstage-rag-env RAG_API_KEY=... LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... CORS_ORIGINS=...
modal deploy modal_app.py
```
O `modal_app.py` serve o mesmo `app` com `@modal.asgi_app()`, Volume `backstage-rag-data` em `/data` e `RAG_DATA_DIR=/data/data_full`. `min_containers=1` evita cold start, mas cobra a GPU parada: use no dia da apresentação.

## Testes
```bash
cd backend
pip install -r requirements-test.txt     # sem torch, chromadb nem bm25s
pytest -q
```
Os testes usam um embedder falso (bag-of-words) com o retrieval de verdade em numpy e um LLM falso. Não baixam modelos nem precisam de dados.
