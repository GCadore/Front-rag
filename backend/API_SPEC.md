# Especificação da API do Backstage RAG (`api.py`)

Documento para implementar o backend que liga o front em Next ao RAG (Chroma + BM25) e ao LLM (Qwen).
O front chama uma route do Next (`/api/chat`, `/api/triage`), que repassa para esta API. O browser nunca fala direto com a API nem com o LLM.

## 1. Stack
- Python 3.11, FastAPI + Uvicorn, Pydantic v2.
- `sentence-transformers` com `BAAI/bge-m3` (embedding da pergunta, 1024 dims, normalizado, fp16 se houver GPU).
- `chromadb` (PersistentClient, métrica cosseno), `bm25s` (+ PyStemmer) para BM25.
- Reranker opcional: `BAAI/bge-reranker-v2-m3` (via `sentence_transformers.CrossEncoder`).
- LLM via SDK `openai` com API compatível com OpenAI: Ollama local (`http://localhost:11434/v1`), vLLM no Modal ou RunPod. Trocar só por variável de ambiente.

## 2. Variáveis de ambiente (`.env`)
```
RAG_DATA_DIR=data_full
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama            # qualquer string no Ollama
LLM_MODEL=qwen2.5:7b          # no vLLM: Qwen/Qwen2.5-7B-Instruct
RAG_API_KEY=troque-isto       # o Next manda no header x-api-key
EMBED_DEVICE=cuda             # ou cpu
ENABLE_RERANKER=true
CORS_ORIGINS=http://localhost:3000
```

## 3. Dados já existentes (não regerar)
Estrutura em `RAG_DATA_DIR`:
```
data_full/
  chunks/chunks.jsonl         # chunks do índice base
  index/                      # índice "base"
    chroma/                   # coleção "backstage_chunks"
    bm25/                     # bm25s.BM25.load(...) + bm25_ids.json
    embeddings.npy, ids.json
  index_lean/                 # índice "enxuto"
    chroma/, chunks.jsonl, embeddings.npy, ids.json   (sem bm25: construir na subida, ver 6)
  addons/{changelog,commit,review}/   # extras: chunks.jsonl, embeddings.npy, ids.json
  index_logico/               # (em breve) mesma estrutura do index_lean
labels.json                   # labels do repo: [{name, description, color}]
```
O nome da coleção Chroma está em `config.yaml`, em `embed.chroma_collection` (`backstage_chunks`). Leia o `config.yaml` em vez de deixar o nome fixo no código. `query_demo.py` tem um exemplo funcionando de busca densa e BM25 (inclusive o stemmer usado no BM25, em `05b_bm25_index.get_stemmer`). Reaproveite esse código.

Formato de um chunk (linha do `chunks.jsonl`):
```json
{"id": "issue-119-000",
 "text": "[ISSUE #119] Error when running `yarn start` | labels: type:bug, area:documentation | estado: closed\n\n...",
 "metadata": {"type": "issue", "number": 119, "created_at": 1582888475,
   "url": "https://github.com/backstage/backstage/issues/119",
   "labels": "type:bug|area:documentation", "state": "closed",
   "doc_id": "issue-119", "title": "Error when running `yarn start`",
   "section": "", "chunk_index": 0, "n_tokens": 681, "duplicates": ""}}
```
`metadata.type` pode ser `issue`, `pr`, `comment`, `doc` ou `adr` (e, nos extras, `changelog`, `commit` ou `review`). Use `doc_id` para agrupar chunks do mesmo documento.

## 4. Endpoints

### `GET /health`
Retorna `{"status":"ok","indices":["base","enxuto",...],"llm":"<LLM_MODEL>","reranker":true}`.

### `GET /labels`
Retorna a lista de `labels.json` filtrada para triagem: prefixos `type:`, `area:`, `integration:`, `domain:` e também `needs:repro` e `needs:more-info`.

### `POST /chat`: pergunta livre sobre o Backstage
Request:
```json
{
  "messages": [{"role": "user", "content": "Como funciona o Scaffolder?"}],
  "config": {
    "rag": true,
    "index": "base",            // "base" | "enxuto" | "base_extras" | "logico"
    "search": "dense",          // "dense" | "bm25" | "hybrid"
    "reranker": true,
    "guardrails": true,
    "top_k": 8
  },
  "stream": true
}
```
Fluxo:
1. Pega a última mensagem do usuário como pergunta. Para seguir a conversa, inclui no máximo as 6 mensagens anteriores no prompt.
2. Se `rag=false`: chama o LLM sem contexto. A resposta sai com `sources: []` e `rag: false`. É o modo "sem RAG" da comparação.
3. Se `rag=true`: faz o retrieval (seção 5), aplica os guardrails de entrada (seção 7) e monta o prompt com os trechos numerados `[1]..[k]`.
4. Chama o LLM com `temperature=0.1`.
5. Aplica os guardrails de saída: remove citações `[n]` que não existem entre os trechos.

Resposta sem streaming:
```json
{
  "answer": "O Scaffolder cria componentes a partir de templates [1][3]...",
  "sources": [
    {"n": 1, "id": "doc-...-002", "doc_id": "...", "type": "doc", "title": "...",
     "url": "https://...", "snippet": "primeiros ~300 caracteres", "score": 0.83}
  ],
  "rag": true,
  "config": { ...ecoa o config efetivo... },
  "timings_ms": {"retrieval": 120, "rerank": 80, "llm": 2400, "total": 2650},
  "refused": false
}
```
Resposta com streaming (`stream=true`): use Server-Sent Events (`text/event-stream`) com estes eventos, nesta ordem:
```
event: sources   data: {"sources":[...]}           # logo após o retrieval
event: token     data: {"t":"pedaço de texto"}     # vários
event: done      data: {"timings_ms":{...},"refused":false,"removed_citations":[...]}
event: error     data: {"message":"..."}           # se der erro
```

### `POST /triage`: triagem de uma issue nova
Request:
```json
{"title": "Scaffolder fails with GitHub app auth",
 "body": "texto da issue (markdown, pode ter template e logs)",
 "config": { ...igual ao /chat... }}
```
Fluxo:
1. Limpa o corpo antes da busca: remove comentários HTML `<!-- -->`, títulos e checkboxes vazios do template, e corta blocos de log muito longos (fica só com as 15 primeiras linhas de cada bloco de código). Use `title + "\n" + body_limpo` como query.
2. Faz o retrieval (seção 5) com `top_k` (padrão 10).
3. Chama o LLM pedindo **JSON estrito** (com `response_format={"type":"json_object"}`; no vLLM também dá pra usar `guided_json`) no schema abaixo.
4. Valida com Pydantic. Se falhar, tenta mais uma vez com uma mensagem de correção. Se falhar de novo, devolve `refused: true` com o erro.
5. Guardrails de saída:
   - `labels`: só aceita labels de `GET /labels`.
   - `related`: só aceita ids que estão entre os trechos recuperados. Completa url, título e tipo a partir dos metadados, e nunca com o que o modelo escreveu.
   - `explanation`: remove citações `[n]` inválidas.

Resposta:
```json
{
  "labels": [{"name": "area:scaffolder", "confidence": "alta"}, {"name": "type:bug", "confidence": "media"}],
  "component": "scaffolder",
  "related": [
    {"n": 2, "doc_id": "issue-21034", "type": "issue", "number": 21034, "title": "...",
     "url": "https://github.com/backstage/backstage/issues/21034", "state": "closed",
     "reason": "mesmo erro de auth com GitHub App", "score": 0.79}
  ],
  "docs": [{"n": 4, "doc_id": "...", "type": "doc|adr", "title": "...", "url": "..."}],
  "needs_more_info": false,
  "explanation": "Texto curto com citações [2][4].",
  "sources": [ ...igual ao /chat... ],
  "removed": {"labels": ["area:inexistente"], "related": ["issue-999999"]},
  "timings_ms": {...},
  "refused": false
}
```
Schema que o LLM deve gerar (no prompt, o modelo devolve só os campos abaixo e a API completa o resto):
```json
{"labels": [{"name": "string", "confidence": "alta|media|baixa"}],
 "component": "string|null",
 "related": [{"n": 1, "reason": "string"}],
 "docs": [{"n": 3}],
 "needs_more_info": false,
 "explanation": "string com citações [n]"}
```

### `POST /compare`: comparação lado a lado (tela "Comparar")
Request: `{"title": "...", "body": "...", "configs": [{...config A...}, {...config B...}], "mode": "triage" | "chat"}`.
Roda as configurações em paralelo (`asyncio.gather`) e devolve `{"results": [respostaA, respostaB]}`, cada uma no formato do endpoint correspondente. São no máximo 4 configurações.

## 5. Retrieval
Função `retrieve(query, config) -> list[Hit]`, com `Hit = {id, doc_id, text, metadata, score}`.

1. **Índice:** `base` usa `index/`, `enxuto` usa `index_lean/`, `logico` usa `index_logico/`. `base_extras` usa o base mais os addons (ver item 5).
2. **Dense:** embedding da query com o BGE-M3 (`normalize_embeddings=True`), `collection.query(n_results=50)`, e `score = 1 - distance`.
3. **BM25:** `bm25s` com o mesmo tokenizer, stopwords e stemmer do `config.yaml`, pegando os top 50.
4. **Hybrid:** RRF entre dense e BM25, com `score = Σ 1/(rrf_k + rank)`. O `rrf_k` está em `config.yaml` (`retrieval.rrf_k`, padrão 60).
5. **base_extras:** monta na subida uma busca densa exata em numpy sobre `embeddings.npy` do base mais o de cada addon (vetores normalizados, então é só produto escalar) e um BM25 em memória sobre os textos. Mais simples que criar outra coleção no Chroma.
6. **Diversidade por fonte:** pegue no máximo 3 chunks por `doc_id` e garanta pelo menos 1 de cada tipo presente (issue/pr, doc/adr) quando houver resultado com score razoável. Na nossa avaliação, separar por fonte subiu o Recall@10 de 0,48 para 0,65.
7. **Reranker** (se `config.reranker`): reordena os top 50 com `CrossEncoder("BAAI/bge-reranker-v2-m3")` usando pares (query, text) e passa a usar o score do reranker.
8. Retorna os `top_k` finais. Junte chunks vizinhos do mesmo `doc_id` num trecho só e limite o contexto total a ~6000 tokens.

## 6. Inicialização (lifespan do FastAPI)
- Carrega o BGE-M3 e o reranker **uma vez**, além de todos os índices disponíveis em `RAG_DATA_DIR` (pule os que não existirem e liste-os em `/health`).
- O `enxuto` não tem BM25 salvo. Construa na subida a partir de `index_lean/chunks.jsonl`, com as mesmas configurações, e salve em `index_lean/bm25/` para as próximas vezes.
- Carrega `labels.json`.

## 7. Guardrails
**Entrada:**
- Se o melhor score depois do retrieval for menor que `MIN_SCORE` (configurável: 0,35 no dense, 0,0 no reranker com score em logit, a calibrar), não chama o LLM e devolve `refused: true` com `answer: "Não encontrei nada sobre isso na base do Backstage."`.
- Limita o tamanho da entrada a 20 mil caracteres.

**Prompt de sistema** (pt-BR, guardar em `config.yaml` ou `prompts/`):
```
Você é um assistente de triagem de issues do repositório backstage/backstage.
Responda SOMENTE com base nos trechos fornecidos em CONTEXTO, numerados [1]..[k].
Cite o número do trecho em toda afirmação, assim: [2].
Se o contexto não tiver a resposta, diga que não encontrou na base. Não invente issues, PRs, links, versões ou labels.
Responda em português.
```
Com `guardrails=false`, use um prompt simples, sem essas regras, para comparar.

**Saída:**
- Remove citações `[n]` com n fora de 1..k e registra em `removed_citations`.
- No /triage, valide labels e related como descrito na seção 4.

## 8. Segurança e operação
- Exige o header `x-api-key == RAG_API_KEY` em tudo menos `/health`.
- CORS só para `CORS_ORIGINS`.
- Timeout de 120 s no LLM. Se der erro no LLM, devolve 502 com uma mensagem amigável.
- Loga cada requisição em JSONL (`logs/requests.jsonl`) com config, ids recuperados, scores, timings e o que os guardrails removeram. Esses logs servem para a avaliação e para a apresentação.

## 9. Lado do Next (route handler)
`app/api/triage/route.ts` (e `/api/chat`, `/api/compare`, iguais) repassa o body para `${RAG_API_URL}/triage` com o header `x-api-key: process.env.RAG_API_KEY` e devolve o `response.body` direto, o que preserva o SSE. O front manda o `config` montado a partir da sidebar: RAG → `rag`, Índice → `index`, Busca → `search`, Reranker → `reranker`, Guardrails → `guardrails`.

## 10. Testes mínimos (pytest)
- Com `rag=true`, `/chat` devolve `sources` não vazio para "Como funciona o Scaffolder?".
- Com `rag=false`, `sources` sai vazio.
- `/triage` nunca devolve label fora de `/labels` nem `related` fora dos trechos recuperados. Teste com um LLM falso (mock) que responde label e id inventados.
- Pergunta fora do tema ("receita de bolo") com guardrails ligados devolve `refused: true`.
- Sem o header `x-api-key`, a API devolve 401.

## 11. Como rodar
```
pip install -r requirements.txt fastapi uvicorn openai python-dotenv
uvicorn api:app --port 8000 --reload
```
No Modal: o mesmo `app` FastAPI pode ser servido com `@modal.asgi_app()`, montando o Volume `backstage-rag-data` em `/data` com `RAG_DATA_DIR=/data/data_full`.
