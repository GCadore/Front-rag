# Como rodar (front + API do RAG + LLM no Modal)

```
navegador ──> Next (npm run dev, localhost:3000)
                └─ /api/* (servidor do Next, com RAG_API_KEY) ──> API do RAG no Modal (FastAPI, GPU L4)
                                                                    ├─ BGE-M3 + reranker + índices (Volume)
                                                                    └─ LLM no Modal (vLLM + Qwen3.5-9B, GPU A10G)
```

Dois apps no Modal, os dois com `min_containers=0` (sem uso não cobram) e desligando depois de 5 min parados:

| App (padrão) | Arquivo | O que faz | GPU |
|---|---|---|---|
| `backstage-rag-api` | `backend/modal_app.py` | FastAPI: `/health`, `/chat` (com SSE), `/triage`, `/compare`, `/labels` | L4 |
| `backstage-rag-llm` | `modal/llm_qwen.py` | vLLM com o `Qwen/Qwen3.5-9B` (pesos em fp8), API no formato da OpenAI em `/v1` | A10G |

URLs da conta do Gustavo (`gucadore2005`):
- API: `https://gucadore2005--backstage-rag-api-fastapi-app.us-east.modal.run`
- LLM: `https://gucadore2005--backstage-rag-llm-serve.us-east.modal.run/v1`

Em outra conta, o formato é `https://<sua-conta>--<app>-<função>.modal.run`; o `deploy_modal.py` mostra as URLs.

## Rodar o front (dia a dia)

```bash
npm install          # só na primeira vez
npm run dev          # http://localhost:3000
```

O `.env.local` precisa de:

```
RAG_API_URL=https://<sua-conta>--backstage-rag-api-fastapi-app.us-east.modal.run
RAG_API_KEY=<a mesma do secret backstage-rag-keys>
MOCK_API=false
```

**Primeira pergunta depois de um tempo parado:** a API e o LLM ligam do zero (cold start). A API leva
uns 35 a 60 s e o LLM ~1,5 min (no primeiríssimo deploy, ~4 min, porque compila e guarda o cache). As routes do Next esperam até 300 s, e as próximas perguntas
saem em poucos segundos. Antes de apresentar, mande uma pergunta qualquer uns 5 min antes pra
"acordar" os dois apps.

## Pra quem clonou (cada um com a própria conta do Modal)

Precisa de Python 3.10+, Node 20+ e uma conta no [Modal](https://modal.com), que dá créditos mensais
grátis no plano Starter.

```bash
# 1. Cliente do Modal (1.6.2 ou mais novo) + login na SUA conta
pip install -U "modal>=1.6.2"
modal setup

# 2. Setup (uma vez por conta): cria o secret com chaves aleatórias, cria o Volume e baixa os
#    índices do Google Drive direto pro Modal (~3 min), e pré-baixa os pesos do Qwen (~5 min)
python scripts/setup_modal.py          # Windows: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
                                       # Linux/Mac: ./scripts/setup.sh

# 3. Deploy do LLM + API (grava o RAG_API_URL no .env.local e mostra as URLs)
python scripts/deploy_modal.py --check # ou scripts\deploy.ps1 / ./scripts/deploy.sh

# 4. Front
npm install
npm run dev
```

O setup cria o `.env.local` a partir do `.env.example` com o `RAG_API_KEY` novo, e o deploy
preenche o `RAG_API_URL`. Se preferir fazer à mão: `cp .env.example .env.local` e cole a URL da
API e a chave.

**Usar o deploy de outra pessoa:** não precisa de Modal nenhum. Basta colocar no `.env.local` o
`RAG_API_URL` e o `RAG_API_KEY` que o dono do deploy passar (por mensagem privada, nunca no git), e
rodar `npm install && npm run dev`. O custo de GPU fica na conta do dono.

### O que o setup faz

- **Secret** `backstage-rag-keys`: `RAG_API_KEY` (o Next manda no header `x-api-key`) e `LLM_API_KEY`
  (a API usa pra falar com o vLLM). Se o secret já existir, ele não mexe. `--rotate-keys` gera chaves
  novas e atualiza o `.env.local`.
- **Volume** `backstage-rag-data`, que é a pasta `data_full`: `modal run backend/modal_app.py::setup`
  baixa as partes das pastas públicas do Drive (base, enxuto, lógico e base com extras), junta, extrai e
  gera os BM25 que não vêm no Drive (enxuto e base com extras), com o mesmo tokenizer do
  `05b_bm25_index.py`. Só baixa o que falta (`--force` baixa de novo, `--only base,logico` escolhe).
  - Alternativa sem Drive, com um `data_full/` já extraído no seu PC:
    `modal volume put backstage-rag-data data_full/ /`
- **Pesos do Qwen** no Volume `huggingface-cache` (`modal run modal/llm_qwen.py::download_model`).
  O BGE-M3 e o reranker já vão dentro da imagem da API no build.

### Nomes e opções (variáveis de ambiente na hora do setup/deploy)

| Variável | Padrão | Para quê |
|---|---|---|
| `RAG_API_APP` | `backstage-rag-api` | nome do app da API |
| `RAG_LLM_APP` | `backstage-rag-llm` | nome do app do LLM (a API acha a URL dele sozinha) |
| `RAG_MODAL_VOLUME` | `backstage-rag-data` | Volume com os índices |
| `RAG_MODAL_SECRET` | `backstage-rag-keys` | secret com as chaves |
| `API_GPU` | `L4` | GPU da API (`T4` sai mais barato) |
| `LLM_MODEL_ID` | `Qwen/Qwen3.5-9B` | modelo do vLLM |
| `LLM_GPU` | `A10G` | GPU do LLM |
| `LLM_QUANTIZATION` | `fp8` | `none` só em GPU de 48 GB ou mais (L40S, A100) |
| `LLM_MAX_MODEL_LEN` | `32768` | contexto máximo |
| `LLM_BASE_URL` | vazio | vazio usa o app do LLM da mesma conta; senão, outra URL `.../v1` |

Exemplo (PowerShell): `$env:API_GPU="T4"; python scripts/deploy_modal.py --api-only`

## Deploy de novo (mudou código)

```bash
python scripts/deploy_modal.py --api-only   # mudou algo em backend/
python scripts/deploy_modal.py --llm-only   # mudou modal/llm_qwen.py
python scripts/deploy_modal.py              # os dois
```

Equivalente direto: `modal deploy backend/modal_app.py` e `modal deploy modal/llm_qwen.py`.

**Atenção:** faça deploy só com o cliente `modal` 1.6.2 ou mais novo (`modal --version`). Um deploy
feito com o 1.6.1 subiu containers que quebravam ao iniciar (erro de import dentro do Modal) e a
API ficou fora do ar até um novo deploy com o 1.6.2. Os scripts já checam a versão.

## Parar e custos

- `modal app stop backstage-rag-api` e `modal app stop backstage-rag-llm` derrubam os apps (pra
  voltar, faça o deploy de novo). Sem isso eles já ficam parados quando ninguém usa, porque
  `min_containers=0`.
- Preços aproximados do Modal (confira em <https://modal.com/pricing>): A10G ≈ US$ 1,10/h, L4 ≈
  US$ 0,80/h e T4 ≈ US$ 0,59/h, cobrados por segundo só enquanto o container está ligado. Cada
  "sessão" de uso paga o tempo de uso mais 5 min de espera: uma hora de testes com os dois apps sai
  por uns US$ 2.
- No dia da apresentação, `min_containers=1` nos dois `@app.function` evita o cold start, mas cobra
  ~US$ 1,90/h mesmo parado. Volte pra 0 depois.
- Logs: `modal app logs backstage-rag-api`. O log de cada requisição (scores e trechos) fica no Volume
  em `logs/requests.jsonl`: `modal volume get backstage-rag-data logs/requests.jsonl .`

## Trocar o LLM pelo Ollama (local, sem Modal)

1. Instale o [Ollama](https://ollama.com) e rode `ollama pull qwen3.5:9b` (versão quantizada; com GPU de 8 GB
   ou mais fica rápido, só no processador funciona, mas fica lento).
2. Rode a API localmente (`cd backend`, `pip install -r requirements.txt`, `data_full/` extraído) com
   este `backend/.env`:
   ```
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_API_KEY=ollama
   LLM_MODEL=qwen3.5:9b
   LLM_ENABLE_THINKING=false
   ```
   e `uvicorn api:app --port 8000`. No `.env.local` do front: `RAG_API_URL=http://localhost:8000`.
3. Também dá pra deixar a API no Modal e só o LLM no seu PC, desde que o Ollama esteja exposto na
   internet (ngrok, por exemplo): `LLM_BASE_URL=https://<seu-tunel>/v1 python scripts/deploy_modal.py --api-only`.

O pensamento do Qwen3.5 (thinking) fica desligado por padrão: o cliente manda
`chat_template_kwargs: {"enable_thinking": false}` (no Ollama, `reasoning_effort: "none"`). Pra ligar,
use `LLM_ENABLE_THINKING=true`, que deixa as respostas mais lentas.

## Pendências

- **MIN_SCORE (guardrails):** valores provisórios, medidos com 10 perguntas do tema e 5 fora do tema
  no índice base: `MIN_SCORE_DENSE=0.55` (tema 0,64 a 0,79; fora 0,39 a 0,52), `MIN_SCORE_RERANK=-1.0`
  (tema 2,9 a 6,6, mas uma pergunta em português no chat deu 0,24; fora -9,0 a -2,3) e BM25 sem corte,
  porque os dois grupos se sobrepõem. Já estão no deploy (`backend/modal_app.py`) e no
  `backend/.env.example`. Pra recalibrar, use `logs/requests.jsonl` (campo `top_scores` de cada
  pedido): umas 20 perguntas boas e umas 10 fora do tema, com o corte entre os dois grupos.
- `modal/retrieve_endpoint.py` é um exemplo antigo e não é usado; o deploy usa `backend/modal_app.py`.
