# Backstage RAG — front end

Interface em Next.js (chat, triagem e comparação) que conversa com a API em Python do RAG (`backend/`, especificada em `backend/API_SPEC.md`).

## Fluxo

```
navegador ──> /api/chat | /api/triage | /api/compare   (routes do Next, servidor)
                 └─ POST ${RAG_API_URL}/chat|/triage|/compare   header x-api-key: RAG_API_KEY
navegador <── resposta da API como veio (SSE no /chat; JSON na triagem e na comparação)
```

As routes do Next são só um proxy: repassam o body, a chave fica no servidor e o `response.body` volta direto, o que preserva o SSE. Busca, reranker, LLM e guardrails ficam todos na API em Python. Também há `GET /api/labels` e `GET /api/health`.

Se a API não responder, a route devolve 502 com `{message}` e a interface mostra o aviso.

## Rodar

```bash
npm install
cp .env.example .env.local   # RAG_API_URL e RAG_API_KEY (a mesma chave da API)
npm run dev                  # http://localhost:3000
```

A API sobe à parte (`uvicorn api:app --port 8000`, ver `backend/API_SPEC.md`).

Com `MOCK_API=true` as routes respondem sozinhas com dados fake (`lib/mock-api.ts`), nos mesmos formatos da API, pra testar a interface sem backend. Os trechos e scores mudam com a configuração; perguntas com "receita" ou "futebol" são recusadas; sem RAG a resposta inventa versão, issue e link; e há sempre uma citação inválida, uma label inexistente e um relacionado inventado pra mostrar os guardrails.

## Observações

- Os scripts usam `--no-experimental-webstorage` porque o Node 25 quebra o Next 15 sem isso.
- As routes aceitam até 300 s (`maxDuration`) por causa da partida a frio do LLM. Se passar de ~12 s, a interface avisa que o modelo está ligando.

## Contra alucinação

Os guardrails rodam na API (seção 7 da spec); o front só mostra o resultado:

- **Recusa** (`refused: true`): quando o melhor score fica abaixo do mínimo, o modelo nem é chamado e aparece "Não encontrei nada sobre isso na base do Backstage.".
- **Chat**: as citações `[n]` que não existem vêm em `removed_citations`; o front tira do texto e mostra um aviso.
- **Triagem**: labels fora de `/labels` e relacionados fora dos trechos recuperados vêm em `removed` e aparecem num bloco "Removido pelos guardrails".

## Painel de configuração, comparação e métricas

- **Barra lateral** (todas as páginas): liga e desliga o RAG, escolhe o índice (base, enxuto, base com extras, lógico) e a busca (dense, BM25, híbrida) e liga e desliga o reranker e os guardrails. A escolha fica salva no navegador e vai em cada requisição como `config` (`rag`, `index`, `search`, `reranker`, `guardrails`; o chat manda `top_k: 8`, a triagem deixa a API usar o padrão 10).
- **Comparar** (`/comparar`): uma chamada a `/api/compare` com as duas configurações; a API roda as duas em paralelo e as respostas aparecem em duas colunas, com o selo "mais rápida". Há atalhos: com RAG vs sem RAG, base vs enxuto, híbrida vs BM25, com vs sem reranker e com vs sem guardrails.
- **Métricas** embaixo de cada resposta (`timings_ms`): tempo total, busca, rerank e LLM, quantidade de trechos, melhor score, a configuração usada e a lista de trechos (título, tipo, trecho e score). Os trechos citados na resposta ficam marcados como "usado".
