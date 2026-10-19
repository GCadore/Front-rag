# Decisões de arquitetura: triagem de issues do Backstage com RAG

Este documento explica **como o sistema foi montado e por que**. Cada decisão segue o formato de um ADR (Architecture Decision Record): contexto, decisão, vantagens, custos, alternativas e evidência.

**Legenda:**
- **[medido]**: número das nossas baterias de teste (mesmas fontes de `analise_critica.md` e `dados_apresentacao.md`).
- **[projeto]**: justificativa de desenho, sem medição própria.
- **[colega]**: número do relatório do colega.

Tudo foi conferido no código em 19/10/2026: `backend/modal_app.py`, `backend/api.py`, `backend/rag/*.py`, `modal/llm_qwen.py` e o front Next.js (`lib/proxy.ts`, `lib/mock-api.ts`, `lib/types.ts`, `app/api/*`).

---

## 1. Visão geral

Diagrama: **`arquitetura.png`** (fonte em `arquitetura.mmd`).

O sistema tem duas metades:

- **Offline (preparação da base):** coleta do GitHub, limpeza, corte temporal, chunking, embeddings BGE-M3 e BM25. Os índices Chroma + BM25 ficam num **Modal Volume**. Detalhes em `base_documentacao.md`.
- **Online (triagem):** três serviços separados.

| Parte | Tecnologia | Onde roda | Papel |
|---|---|---|---|
| Front | Next.js 15 | PC do usuário (`npm run dev`) | Tela de triagem, chat e comparação |
| Backend | FastAPI | Modal, GPU **L4** | Busca híbrida, montagem do prompt, guardrails |
| LLM | Qwen3.5-9B fp8 no **vLLM** | Modal, GPU **A10G** | Gera a triagem em JSON |

### Caminho de uma triagem

1. O usuário cola título e corpo da issue na tela de triagem.
2. O browser chama `/api/triage` **do próprio Next**. A rota repassa para `POST {RAG_API_URL}/triage` e acrescenta o cabeçalho `x-api-key` do lado do servidor.
3. O backend confere a chave, limpa o corpo da issue e corta a entrada em 20.000 caracteres.
4. Faz a busca híbrida (BM25 + BGE-M3, fusão RRF) no índice pedido e pega os 10 melhores trechos.
5. **Gate de relevância:** se o melhor score denso fica abaixo do mínimo, recusa sem chamar o LLM.
6. Monta o prompt: 42 labels com descrição, 3 exemplos resolvidos, trechos [1]..[10], labels dos 5 vizinhos (só de antes de T) e a issue nova.
7. Chama o vLLM em modo JSON, com temperatura 0,1. Se o JSON não validar, tenta mais uma vez.
8. **Guardrails em código:** remove labels fora da lista e itens ou citações fora do contexto, e normaliza as citações para [n].
9. Completa `related` e `docs` com título, link, número, estado e score **tirados do índice**.
10. Grava o log da requisição no Volume e devolve o JSON. O front monta a tela.

---

## 2. As decisões

### ADR-01: Três partes separadas (front, backend, LLM)

- **Contexto:** precisávamos de uma tela para a demo, de uma API que fizesse a busca e de um LLM. Cada parte tem necessidades diferentes de hardware.
- **Decisão:** front em **Next.js**, backend em **FastAPI** num app do Modal (`backstage-rag-api`) e LLM em **outro app** do Modal (`backstage-rag-llm`).
- **Vantagens:**
  - Cada parte pode ser trocada ou reimplantada sem mexer nas outras. Os deploys v17 e v18 dos guardrails mexeram só no backend. [projeto]
  - Cada uma escala sozinha: o backend aceita até 8 requisições ao mesmo tempo por container, o vLLM até 16. [projeto]
  - Responsabilidades claras: o front só mostra, o backend decide e valida, o LLM só gera texto. Isso facilita testar: o backend tem 103 testes automáticos com serviços falsos injetados (`create_app(services=...)`). [medido: contagem de testes]
- **Custos/trade-offs:** mais peças para configurar (URL, chaves, dois deploys) e uma chamada de rede a mais entre backend e LLM. O script `scripts/deploy_modal.py` faz os dois deploys e grava a URL no `.env.local`, o que reduz esse custo.
- **Alternativas consideradas:** um app único (front + backend + modelo no mesmo processo). **Não comparamos**; a escolha é de projeto.
- **Evidência:** `backend/modal_app.py`, `modal/llm_qwen.py`, `scripts/deploy_modal.py`.

### ADR-02: LLM num serviço próprio, com GPU própria e API compatível com a da OpenAI

- **Contexto:** o backend precisa de GPU para o BGE-M3 e o reranker; o LLM precisa de bem mais memória. Queríamos um modelo aberto.
- **Decisão:**
  - Backend numa **L4** (`API_GPU`, padrão L4), com BGE-M3 e `bge-reranker-v2-m3` **embutidos na imagem** no build: a partida a frio não baixa modelos (`HF_HUB_OFFLINE=1`).
  - **Qwen3.5-9B** servido pelo **vLLM 0.31** numa **A10G** de 24 GB (`LLM_GPU`), com quantização **fp8** e contexto de **32.768 tokens**. O "thinking" do Qwen vem desligado por requisição.
  - O backend fala com o LLM pelo formato da API da OpenAI (`OpenAICompatLLM`). Com `LLM_BASE_URL` vazio, ele **descobre sozinho** a URL do app do vLLM na mesma conta do Modal.
- **Vantagens:**
  - **Trocar de modelo é mudar uma variável:** `LLM_MODEL_ID` no deploy, ou `LLM_BASE_URL` para apontar para outro servidor compatível (Ollama, RunPod...). O código já trata o caso do Ollama. [projeto]
  - **Modelo aberto:** sem API paga por token, e os textos das issues ficam no nosso ambiente. [projeto]
  - **Cabe numa GPU barata:** em fp8 os pesos ocupam ~10 GB e sobra memória para 32k de contexto. Em bf16 deu falta de memória (OOM) na GPU de 24 GB. [projeto, testado na montagem: comentário em `llm_qwen.py`]
  - **Saída JSON nativa:** o backend pede `response_format: json_object` ao vLLM. [projeto]
  - Cada GPU do tamanho certo: a L4 não precisa carregar o LLM, e a A10G não carrega o BGE-M3. [projeto]
- **Custos/trade-offs:** duas GPUs para ligar (duas partidas a frio) e um modelo de 9B, mais fraco que modelos grandes pagos. A latência mediana da triagem é **22,5 s** (p90 **29,9 s**, 864 respostas). [medido]
- **Alternativas consideradas:** API paga (GPT, Claude) ou um modelo maior. **Não comparamos.** Também não comparamos BGE-M3 com outros modelos de embedding.
- **Evidência:** `modal/llm_qwen.py` (`LLM_GPU=A10G`, `LLM_QUANTIZATION=fp8`, `LLM_MAX_MODEL_LEN=32768`), `modal_app.py` (`_resolve_llm_url`, `_download_models`), `rag/llm.py`.

### ADR-03: O browser nunca fala direto com a API (rotas do Next como proxy)

- **Contexto:** a API no Modal é pública na internet e protegida por chave. A chave não pode ir para o navegador.
- **Decisão:** as rotas `/api/triage`, `/api/chat`, `/api/compare`, `/api/labels` e `/api/health` do Next repassam a chamada pelo `lib/proxy.ts`, que acrescenta `x-api-key` com `RAG_API_KEY` **no servidor**.
- **Vantagens:**
  - **A chave não aparece no navegador**: fica só no `.env.local` do servidor Next. [projeto]
  - **Cancelar funciona de ponta a ponta:** o `req.signal` vai junto, então se o usuário para no browser, a chamada ao Modal também é cancelada e não gasta GPU à toa. [projeto]
  - **Streaming preservado:** o corpo volta como veio, com `no-transform` e `X-Accel-Buffering: no`, então o SSE do chat chega pedaço por pedaço. [projeto]
  - Mensagens de erro amigáveis quando a API está fora do ar (502) e `maxDuration = 300 s` nas rotas, para aguentar a partida a frio. [projeto]
  - Sem problemas de CORS: o browser só fala com a própria origem. O backend libera só `http://localhost:3000`. [projeto]
- **Custos/trade-offs:** um salto de rede a mais (browser → Next → Modal).
- **Alternativas consideradas:** chamar o Modal direto do browser, com a chave exposta. Descartada por segurança, sem medição.
- **Evidência:** `lib/proxy.ts`, `app/api/*/route.ts`, `backend/api.py` (`require_api_key` com `secrets.compare_digest`; `CORSMiddleware`).

### ADR-04: Modo de teste sem gastar (`MOCK_API`)

- **Contexto:** cada triagem real liga GPUs no Modal e gasta crédito.
- **Decisão:** com `MOCK_API=true`, as rotas do Next respondem com dados falsos (`lib/mock-api.ts`) **nos mesmos formatos da API**, sem chamar o Modal.
- **Vantagens:**
  - Desenvolver e ajustar a tela **sem custo** e sem esperar partida a frio. [projeto]
  - O mock simula os casos difíceis: pergunta fora do tema ("receita", "futebol") vira recusa, e os scores mudam com a configuração para a tela de comparação mostrar diferença. [projeto]
  - O front pôde ser feito em paralelo com o backend. [projeto]
- **Custos/trade-offs:** o mock pode ficar desatualizado se a API mudar de formato. Hoje está `MOCK_API=false`, então cada triagem no front gasta crédito.
- **Alternativas consideradas:** nenhuma formal.
- **Evidência:** `lib/proxy.ts` (`isMock`), `lib/mock-api.ts`, `app/api/*/route.ts`.

### ADR-05: Configuração por requisição

- **Contexto:** queríamos comparar índices, buscas, reranker e guardrails sem fazer um deploy para cada teste.
- **Decisão:** cada chamada leva um objeto `config` com `rag`, `index`, `search`, `reranker`, `guardrails`, `top_k` e as opções de triagem (`neighbor_labels`, `label_descriptions`, `query_rewrite`, `label_votes`, `split_types`, `bm25_boost`, `related_min_score`). O que não vem na requisição usa o padrão do deploy.
- **Vantagens:**
  - **Baterias de teste sem novo deploy:** as baterias trocaram de configuração só mudando o corpo da requisição; a busca2 teve 216 issues × 4 configurações = 864 respostas. [medido]
  - **Tela de comparação lado a lado:** `/compare` roda até **4 configurações em paralelo** com a mesma issue. [projeto]
  - **Ideias testadas e descartadas continuam disponíveis:** reranker, reescrita da consulta e votação de labels ficam **desligados por padrão**, mas podem ser ligados por requisição. [medido: ver ADR-08]
  - Dá para desligar os guardrails (`guardrails: false`) e ver o modelo "cru", e desligar o RAG (`rag: false`) para comparar com e sem busca. [projeto]
- **Custos/trade-offs:** mais combinações para manter e testar. Os padrões do backend e do front não são idênticos: o schema do backend tem `search: "dense"`, mas o front sempre manda `hybrid`.
- **Alternativas consideradas:** configuração fixa por variável de ambiente. Também existe (é o padrão), mas sozinha exigiria um deploy por teste.
- **Evidência:** `rag/schemas.py` (`RagConfig`, `CompareRequest` com até 4 configs), `rag/pipeline.py` (`effective_config`), `lib/types.ts` (`DEFAULT_CONFIG`).

### ADR-06: Chroma embutido num Modal Volume, com vários índices

- **Contexto:** precisávamos guardar ~39 a 108 mil chunks por índice e ler rápido de dentro da API.
- **Decisão:** **Chroma** em modo embutido (`PersistentClient`, só arquivos, sem servidor), coleção com distância **cosseno (HNSW)**, mais um índice **BM25** (`bm25s`) sobre os mesmos chunks. Tudo fica num **Modal Volume** montado em `/data`. Há quatro índices: **base**, **enxuto**, **lógico** e **base+extras**.
- **Vantagens:**
  - **Sem servidor de banco para manter nem pagar:** o índice é uma pasta, montada pela API. [projeto]
  - **Carregado uma vez por container** (no `lifespan` do FastAPI), e depois cada busca é local. [projeto]
  - **Vários índices na mesma API:** o índice é escolhido por requisição. Foi isso que permitiu comparar as variantes de chunking. [medido: chunks por índice base 39.180, enxuto 28.813, lógico 41.841, base+extras 107.928]
  - **Reproduzível:** `populate_volume` baixa os índices do Google Drive e gera os BM25 que faltam, com o mesmo tokenizer da preparação. [projeto]
  - Metadados (tipo, número, data, url, labels, estado) guardados junto com o vetor. São eles que preenchem os links na tela e permitem o corte por data dos vizinhos. [projeto]
- **Custos/trade-offs:** o Chroma embutido não serve para muitos usuários escrevendo ao mesmo tempo (aqui só lemos). Atualizar a base exige reindexar e subir o Volume de novo.
- **Alternativas consideradas:** banco vetorial com servidor (pgvector, Qdrant, Pinecone). **Não comparamos.**
- **Evidência:** `rag/indices.py` (`ChromaDense`: "métrica cosseno: score = 1 − distância"; `INDEX_DIRS`; `load_base_extras`), `modal_app.py` (`populate_volume`, `DRIVE_BUNDLES`), `base_documentacao.md`.

### ADR-07: Scale-to-zero, com aquecimento antes da demo

- **Contexto:** o orçamento era de créditos do Modal, e o sistema fica parado a maior parte do tempo.
- **Decisão:** nos dois apps, `min_containers=0` e `scaledown_window=300` (o container desliga depois de 5 min sem uso). A API aceita até 8 requisições simultâneas por container (`@modal.concurrent(max_inputs=8)`); o vLLM, até 16.
- **Vantagens:**
  - **Custo zero quando ninguém usa**: só pagamos a GPU enquanto há requisições. [projeto]
  - Todas as baterias, em 17 e 18/10, custaram **~US$ 15,6** de créditos. [medido]
  - Os 5 minutos de espera evitam desligar entre chamadas de uma mesma sessão de testes. [projeto]
- **Custos/trade-offs (partida a frio):**
  - a API leva ~**53 s** para responder ao `/health`, e o primeiro token do LLM ~**81 s**; [medido]
  - a primeira chamada a frio já passou de **150 s** e voltou **HTTP 303** (o Modal redireciona requisições longas); [medido, `teste_demo.md`]
  - por isso o backend espera até 300 s pelo LLM (`LLM_TIMEOUT_S`) e devolve 503 com `Retry-After: 30` se o LLM ainda não subiu. [projeto]
- **Mitigação:** **aquecer** os containers com uma triagem qualquer antes da apresentação, ou usar `min_containers=1` no dia (sem partida a frio, mas a GPU parada é cobrada). [projeto]
- **Alternativas consideradas:** container sempre ligado. Não usado por custo; não medimos o custo diário.
- **Evidência:** `modal_app.py` e `llm_qwen.py` (decorators), `api.py` (`_llm_error`), `teste_demo.md`, `analise_critica.md`.

### ADR-08: Busca híbrida no backend (BM25 + BGE-M3 com RRF)

- **Contexto:** issues têm muitos identificadores exatos (`@backstage/integration`, `RepoUrlPicker`, mensagens de erro) que a busca semântica "borra", mas a semântica acha relatos escritos de outro jeito.
- **Decisão:** fusão **RRF ponderada** com `RRF_W_BM25 = 0,8` e `RRF_K = 30`. Reranker, reescrita da consulta e votação ficam desligados por padrão. No índice lógico, a busca é separada em 6 issues/PRs + 4 docs.
- **Vantagens:**
  - Junta os dois sinais: o BM25 sozinho já ganha do denso (nDCG@10 0,428 × 0,386), e o híbrido ajustado chega a **0,471** (Recall@10 0,589). [medido]
  - Tudo roda dentro do backend, na mesma GPU, sem serviço de busca separado. [projeto]
  - O reranker ficou de fora porque **piorou** a busca (nDCG 0,439 → 0,324) e economiza ~0,3–0,5 s por consulta. [medido]
- **Custos/trade-offs:** o RRF não tem escala absoluta, então o gate de relevância usa o melhor score **denso**. Recall@10 ~0,6: a busca continua sendo o gargalo.
- **Alternativas consideradas:** densa pura, BM25 puro, reranker, blend, reescrita, votação, agrupamento por documento. **Comparamos** (33 variantes de busca); números completos em `analise_critica.md`, Parte 1.
- **Evidência:** `rag/retrieval.py` (`rrf_fuse`, pesos `w_bm25`), `modal_app.py` (`RRF_K`, `RRF_W_BM25`, `RETRIEVAL_SPLIT_TYPES_INDICES=logico`).

### ADR-09: Guardrails como código determinístico, não como outro LLM

- **Contexto:** pedir no prompt "não invente" não garante nada. Precisávamos garantir que o que aparece na tela existe na base.
- **Decisão:** regras fixas em Python (`rag/guardrails.py`), em três momentos:
  1. **Entrada:** corta título em 1.000 e a consulta em 20.000 caracteres.
  2. **Antes do LLM:** se o melhor score fica abaixo do mínimo (`MIN_SCORE_DENSE = 0,55`), **recusa sem chamar o LLM**. O prompt vai na versão estrita.
  3. **Depois do LLM** (`guard_triage`):
     - valida o JSON contra o schema (Pydantic), com **1 nova tentativa** com a mensagem de erro;
     - aceita só labels da lista: **42 labels de triagem**, filtradas das 76 do repositório (prefixos `type:`, `area:`, `integration:`, `domain:` + `needs:repro`, `needs:more-info`);
     - remove related, docs e citações que não apontam para um trecho entregue, e menções `#n` ou URLs que não estão no contexto nem no texto do usuário;
     - deduplica related e docs pelo documento;
     - **`normalize_citations` (v17):** converte `[issue #N]`, `[#n]`, `[1, 3]`, doc_ids e `[issue nova]` em `[n]`;
     - **`fix_index_mentions` (v18):** no texto corrido, troca "issue #K", quando K é o número de um trecho, pelo número real da issue.
  - Tudo o que foi removido vai no campo **`removed`**, e o front mostra numa caixa amarela.
- **Vantagens:**
  - **Rápido e sem GPU:** são comparações de texto e conjuntos, sem chamada extra a modelo. [projeto]
  - **Determinístico:** a mesma resposta do modelo sempre gera a mesma saída. [projeto]
  - **Auditável:** o campo `removed` mostra exatamente o que foi cortado, e as regras têm testes automáticos. [projeto]
  - **Funciona:** na busca2 (864 respostas), **14 labels inventadas** foram barradas e a saída final teve 0 labels fora da lista. Com regras no prompt + filtro, o F1 de labels subiu de **0,72 para 0,78** (30 issues). No chat, **95%** das perguntas fora do tema foram recusadas com guardrails, contra 0% sem. [medido]
  - Pode ser desligado por requisição, o que permitiu medir com e sem. [projeto]
- **Custos/trade-offs:**
  - Regra fixa não entende intenção. Antes da v17, o modelo citava pelo número da issue, e o guardrail apagava referências **corretas** (#34747: 94 related em 29 respostas eram esse erro de formato). [medido] Corrigido nas v17/v18.
  - Quando uma citação é removida, a frase fica com buraco; ainda não reescrevemos a frase.
  - O limiar de 0,55 é **provisório**: os logs para calibrar existem, mas a recalibração ainda não foi feita.
- **Alternativas consideradas:** um LLM juiz checando a resposta em tempo real. Não usado (custo e latência). O juiz LLM só foi usado na avaliação offline.
- **Evidência:** `rag/guardrails.py`, `rag/pipeline.py` (`_triage_llm`, `triage_once`), `backend/tests/`, `analise_critica.md`.

### ADR-10: Contrato JSON estruturado, com links preenchidos pelo índice

- **Contexto:** a tela precisa de campos fixos, e um LLM inventa URLs com facilidade.
- **Decisão:** o modelo responde só um JSON com:
  - `labels` (nome + confiança alta/média/baixa);
  - `component`;
  - `related` (número do trecho `n` + motivo);
  - `docs` (número do trecho `n`);
  - `needs_more_info`;
  - `explanation` com citações [n].
  - O backend troca cada `n` pelos **dados do índice**: `doc_id`, tipo, número, título, URL, estado e score.
- **Vantagens:**
  - **O LLM nunca gera URL nem título:** tudo o que é link vem dos metadados do trecho. [projeto]
  - O front monta a tela direto dos campos, sem interpretar texto livre. [projeto]
  - Fácil de avaliar automaticamente: F1 de labels, related_hit, citações válidas. [projeto]
  - O mesmo formato serve para a tela, para as baterias e para a comparação. [projeto]
- **Custos/trade-offs:** o modelo às vezes erra o formato (por isso a nova tentativa e a normalização). No colega, forçar o JSON schema no vLLM causou loop em 18% das respostas com RAG; nós usamos só o modo `json_object` com validação no backend. [colega]
- **Alternativas consideradas:** texto livre com links. Não comparamos.
- **Evidência:** `rag/schemas.py` (`TriageLLMOutput`, `TriageResponse`), `rag/guardrails.py` (`related_from_hit`, `_doc_from_hit`), `components/triage-result.tsx`.

### ADR-11: Corte temporal T = 22/04/2026, também nos vizinhos

- **Contexto:** se a issue de teste ou o PR que a resolveu estivessem no índice, o resultado seria artificialmente bom.
- **Decisão:** tudo criado a partir de **T = 22/04/2026** fica fora do índice e vira teste. As labels dos vizinhos (ajuda A) também respeitam T (`TRIAGE_NEIGHBOR_CUTOFF`): vizinhos criados depois de T são ignorados.
- **Vantagens:**
  - **Avaliação sem vazamento:** 0 chunks com data ≥ T. [medido]
  - Simula o uso real: o sistema só conhece o passado da issue nova. [projeto]
  - As refs do próprio texto da issue de teste foram mascaradas como `[ref]` na avaliação. [medido]
- **Custos/trade-offs:** a base não tem os últimos ~6 meses. As labels do gabarito são as atuais, não as de T.
- **Alternativas consideradas:** divisão aleatória. Descartada porque vazaria informação do futuro.
- **Evidência:** `config.yaml` (`cutoff`), `modal_app.py` (`TRIAGE_NEIGHBOR_CUTOFF`), `rag/triage_aids.py` (`neighbor_labels`).

### ADR-12: Log de cada requisição no Volume

- **Contexto:** precisávamos de dados para calibrar o limiar de recusa e analisar as baterias.
- **Decisão:** cada chamada grava uma linha em `requests.jsonl` dentro do Volume (`LOG_DIR=/data/logs`): configuração, consulta (até 1.000 caracteres), trechos e scores, melhor score de cada etapa, limiar usado, tempos, o que foi removido e se houve recusa.
- **Vantagens:**
  - Base para **calibrar o MIN_SCORE** com dados reais. [projeto]
  - Persiste entre containers, mesmo com scale-to-zero. [projeto]
  - Falha no log nunca derruba a requisição. [projeto]
- **Custos/trade-offs:** guarda o texto da consulta. A calibração **ainda não foi feita**: o limiar de 0,55 continua provisório.
- **Evidência:** `rag/reqlog.py`, `rag/pipeline.py` (`_log`), `modal_app.py` (`LOG_DIR`), `backend/.env.example` (TODO de recalibrar).

### Outras decisões menores (do código)

- **Autenticação no backend:** todas as rotas, menos `/health`, exigem `x-api-key`, comparada em tempo constante (`secrets.compare_digest`). As chaves ficam num **Modal Secret** (`backstage-rag-keys`), nunca no código. O vLLM também exige chave (`--api-key`). [projeto]
- **`/health` aberto:** mostra os índices carregados, o modelo e se o reranker está disponível. Serve para aquecer e checar a API antes da demo. [projeto]
- **Erro amigável quando o LLM está frio:** 503 com `Retry-After`, e o front mostra uma mensagem em vez de quebrar. [projeto]

---

## 3. Tabela-resumo

| # | Decisão | Vantagem principal | Trade-off |
|---|---|---|---|
| 01 | Front, backend e LLM separados | Troca e deploy de cada parte sem mexer nas outras | Mais configuração e um salto de rede |
| 02 | LLM aberto (Qwen3.5-9B fp8, vLLM, A10G) com API da OpenAI | Sem API paga; trocar de modelo é mudar uma variável; cabe em 24 GB | Modelo menor; duas GPUs; ~22,5 s por triagem |
| 03 | Next como proxy | Chave fora do browser; cancelamento e streaming preservados | Um salto de rede a mais |
| 04 | `MOCK_API` | Desenvolver a tela sem gastar crédito | Mock pode desatualizar |
| 05 | Config por requisição | Baterias e comparação lado a lado sem deploy | Mais combinações para manter |
| 06 | Chroma embutido no Volume, 4 índices | Sem servidor de banco; índice escolhido por requisição | Atualizar exige reindexar; não comparamos bancos |
| 07 | Scale-to-zero | Custo zero parado; ~US$ 15,6 em todos os testes | Partida a frio de ~1 min (até >150 s) |
| 08 | Busca híbrida RRF (w 0,8, k 30) | nDCG@10 0,471, melhor que denso e BM25 sozinhos | Recall@10 ~0,6 ainda é o gargalo |
| 09 | Guardrails em código | Rápido, sem GPU, determinístico, auditável (`removed`) | Regra fixa pode apagar referência boa; limiar provisório |
| 10 | Contrato JSON + links do índice | LLM nunca gera URL; tela e avaliação simples | Erros de formato exigem retry e normalização |
| 11 | Corte T também nos vizinhos | Avaliação sem vazamento (0 chunks ≥ T) | Base sem os últimos meses |
| 12 | Log no Volume | Dados para calibrar a recusa e auditar | Calibração ainda não feita |

---

## 4. Limitações da arquitetura (assumir na apresentação)

- **Não comparamos arquiteturas alternativas:** API paga × modelo próprio, banco vetorial com servidor × Chroma, outros modelos de embedding. São escolhas de projeto, justificadas por custo, privacidade e simplicidade.
- **Índice padrão do front é `base`**, mas o melhor número medido é **lógico + split** (nDCG +0,019 [+0,001; +0,038], ganho pequeno e sempre nas mesmas 82 issues). Decidir antes da apresentação ou explicar.
- **Next.js 15.3.3** tem alerta de segurança (**CVE-2025-66478**): atualizar antes de publicar fora do PC.
- **Partida a frio:** sem aquecimento, a primeira chamada da demo pode levar mais de 2 minutos.
- **`MIN_SCORE` provisório (0,55):** os logs para recalibrar existem, mas a recalibração não foi feita.
- **O front roda local** (`npm run dev`); não há deploy público do front.

---

## 5. Versão pra slide (1 slide)

**Título:** Arquitetura: por que assim

**Esquerda:** `arquitetura.png`

**Direita, 4 porquês:**
- **3 partes separadas:** front, busca + guardrails e LLM trocam e escalam sozinhos.
- **Modelo aberto no Modal (Qwen 9B fp8, vLLM):** sem API paga, dados no nosso ambiente, cabe em 24 GB.
- **Scale-to-zero:** custo zero parado; todos os testes por ~US$ 15,6 (preço: ~1 min de partida a frio).
- **Guardrails em código + links do índice:** o LLM não inventa label nem URL (14 labels inventadas barradas em 864 respostas).

**Fala sugerida (~40 s):** "A gente separou o sistema em três partes: a tela, o backend que faz a busca e confere a resposta, e o modelo. Cada uma roda sozinha no Modal e escala a zero, então quando ninguém usa o custo é zero; todos os nossos testes custaram uns 15 dólares. O modelo é aberto, o Qwen de 9 bilhões, e fala o formato da OpenAI, então trocar de modelo é mudar uma variável. E o que garante que ele não inventa não é o prompt: é o código, que confere cada label e cada citação, e os links vêm sempre do índice, nunca do modelo."

---

## 6. Possíveis perguntas da banca

**"Por que não usaram uma API paga, como GPT ou Claude?"**
Por custo, privacidade e controle: com modelo aberto não pagamos por token e as issues não saem do nosso ambiente. Mas não comparamos com API paga; é uma escolha de projeto, não um resultado.

**"Por que o LLM fica num serviço separado?"**
Porque precisa de outra GPU e de outro ciclo de deploy. Separado, os deploys v17 e v18 dos guardrails mexeram só no backend, sem reimplantar o modelo, e trocar de modelo é mudar `LLM_MODEL_ID` ou `LLM_BASE_URL`.

**"Por que Chroma e não um banco vetorial de verdade?"**
O Chroma embutido é só uma pasta: sem servidor para manter, cabe num Volume do Modal e carrega junto com a API. Para um sistema só de leitura, com até ~108 mil chunks, foi suficiente. Não comparamos com outros bancos.

**"O guardrail não deveria ser um LLM também?"**
Para o que ele faz, não precisa: conferir se uma label está na lista ou se um [n] existe é comparação exata. Em código é rápido, não usa GPU, dá sempre o mesmo resultado e mostra o que cortou. O juiz LLM só foi usado na avaliação offline.

**"E se a primeira chamada demorar na demo?"**
É a partida a frio do scale-to-zero (~1 min, já passou de 150 s). Por isso aquecemos os containers antes; no dia também dá para usar `min_containers=1`.

**"Por que o front usa o índice base se o lógico mediu melhor?"**
A diferença é pequena (nDCG +0,019) e foi sempre medida nas mesmas 82 issues. [Ajustar conforme a decisão do grupo: trocar o padrão para lógico ou manter base como referência.]

**"A chave da API fica exposta?"**
Não. O browser só fala com o Next; a rota do Next acrescenta a chave no servidor. No Modal, as chaves ficam num Secret.
