# Base de dados — qual base, como foi organizada e preparada

Todos os números foram conferidos em 18/10/2026 nos arquivos do pipeline (`/workspace/backstage-rag`: `config.yaml`, scripts `01_`…`06_`, `rag_prep/`, `data_full/reports/*.json`, `data_full/*.log`), em `apresentacao/estatisticas_base.json`, no relatório do colega e no código do nosso backend (`melhorias/work/backend/rag/`). O que não deu para conferir está marcado com ⚠️ e listado no fim.

---

## 1. Fonte

- **Repositório:** `backstage/backstage` no GitHub, branch `master`.
- **Tipos no índice principal:** issues, PRs (com os comentários de cada um), páginas de documentação (`docs/**/*.md|mdx`) e ADRs (`docs/architecture-decisions/adrNNN-*.md`).
- **Fontes extras (só na variante "base + extras"):**
  - changelogs automáticos (`docs/releases/*-changelog.md`, 217 arquivos);
  - comentários inline de revisão de PR;
  - mensagens de commit.
- **Como foi coletado (`01_collect.py`):**
  - API REST do GitHub, endpoints `/issues` (traz issues e PRs) e `/issues/comments`, paginados por cursor (`since` + `sort=updated`), com retomada.
  - Clone parcial do git com checkout esparso só de `docs/` e `.github/` (este último para os templates de issue/PR, usados na limpeza).
  - Docs e ADRs vêm do **último commit antes do corte**: `e2fdc2b6`, de 21/04/2026 (merge do PR #33911).
- **Período coletado:** itens criados de 01/02/2020 a 17/10/2026; o último comentário coletado é de 17/10/2026.
- **Período indexado:**
  - issues de 09/02/2020 a 20/04/2026;
  - PRs de 03/02/2020 a 20/04/2026.
- **Data de corte T = 22/04/2026 00:00 UTC** (data de lançamento do Qwen3.6-27B, `config.yaml`).
  - Tudo criado **antes** de T vai para o índice; o que foi criado **em T ou depois** fica de fora e pode virar teste.
  - **Por quê:** evitar vazamento. A issue de teste e a resposta dela (comentários, PR que a corrigiu) não podem estar no índice. Por isso também caem os comentários escritos depois de T em itens antigos, e PRs mergeados depois de T.
  - A checagem final (`07_sanity_checks.py`) confirma: **0 chunks com `created_at ≥ T`**.

## 2. Organização

- **Unidade = documento** (`03_build_documents.py`), um por item, com id estável:
  - `issue-<n>`, `pr-<n>`, `doc-<caminho>` (ex.: `doc-features/search/index`), `adr-<nnn>`;
  - nas fontes extras: `changelog-<caminho>`; review e commit usam o `pr-<n>` do PR, e commit sem PR identificável vira `commit-<sha>`.
- **Campos do documento:** `doc_id`, `type`, `number`, `title`, `url`, `created_at` (unix), `labels` (`"a|b"`), `state` (estado reconstruído em T), `state_now`, `n_comments`, `text`; docs também têm `path` e `section_root`.
- **Texto de issue/PR:** `# título`, corpo e depois os comentários em ordem cronológica, cada um como `**Comentário de @autor em AAAA-MM-DD:**`, separados por `---`.
- **Chunk:** id `<doc_id>-<nnn>` (ex.: `issue-1234-003`), mais `text` e os metadados `type`, `number`, `created_at`, `url`, `labels`, `state`, `doc_id`, `title`, `section`, `chunk_index`, `n_tokens`, `duplicates`. O mesmo arquivo `chunks.jsonl` alimenta o Chroma e o BM25 (mesmos ids).
- **Documentos indexados: 19.932** = 7.381 issues + 12.112 PRs + 424 docs + 15 ADRs.
  - 6.994 issues têm alguma label.
  - Labels mais comuns: `type:bug` 3.767, `type:suggestion` 2.319, `area:catalog` 906, `area:scaffolder` 631, `area:techdocs` 586.
- ⚠️ **Limitação conhecida:** as labels e o `state_now` são **os de hoje**, não os de T. 280 issues e 1.528 PRs foram atualizados depois de T (o corpo e as labels podem ter mudado).

## 3. Limpeza e filtragem (`02_clean.py`, contagens de `clean_stats.json`)

| Etapa | Brutos | Removidos | Ficaram |
|---|---|---|---|
| **Issues** | 8.021 | criadas ≥ T: **468** · autor bot: **172** | **7.381** |
| **PRs** | 26.900 | criados ≥ T: **1.737** · autor bot: **7.745** · não mergeados antes de T: **2.921** · sem descrição (< 30 caracteres depois da limpeza): **2.385** | **12.112** |
| **Comentários** (dos itens mantidos) | 104.105 no total | criados ≥ T: **573** · de bot: **23.082** · baixo valor ("+1", "same", "thanks", "lgtm", só emoji…): **319** | **50.980** |
| **Docs/ADRs** (`.md`/`.mdx` em `docs/`) | — | changelogs automáticos e arquivos ocultos (`docs/.*`): **222** · índice/template de ADR: **2** · vazios: **3** | **424 docs + 15 ADRs** |

Os 104.105 comentários brutos incluem os dos itens já descartados (29.151), que não são contados por motivo.

- **O que conta como bot:**
  - `user.type == Bot`, login terminando em `[bot]`, ou um dos 18 logins da lista do `config.yaml` (renovate, changeset-bot, github-actions, dependabot, backstage-goalie, codecov, netlify, linux-foundation-easycla, copilot…);
  - usuário apagado ("ghost") também conta como bot.
- **Limpeza do texto** de issues, PRs e comentários:
  - remove comentários HTML (inclusive os não fechados), `Signed-off-by:`, imagens HTML e imagens markdown sem texto alternativo (com texto alternativo, a imagem vira `[imagem: …]`);
  - normaliza CRLF e linhas em branco.
- **Formulários de issue:** remove as seções de metadados ("📜 Issue Labels", "Have you read the Code of Conduct?", "Are you willing to submit PR?") e as seções com resposta `_No response_`, `None`, `N/A` ou vazia.
- **Templates:**
  - remove as linhas fixas do `PULL_REQUEST_TEMPLATE` e as opções de checkbox dos issue forms (`.github/ISSUE_TEMPLATE/*.yaml`), lidas no snapshot de T;
  - **boilerplate estatístico:** remove linhas que aparecem em ≥ 30% dos itens (e pelo menos 5). Só pegou 1 linha nas issues ("- [x] I checked and didn't find similar issue") e nenhuma nos PRs. Títulos `#` e blocos de código nunca são removidos.
- **Docs:** tira o frontmatter (o `title` vem dele) e comentários HTML; nos `.mdx`, tira também imports/exports e as linhas de componentes JSX. Código não é tocado.
- **Changelogs:** os 217 automáticos ficam fora do índice principal. Eles gerariam cerca de 36 mil chunks curtos, repetindo os `CHANGELOG.md` dos pacotes. As 51 notas de versão escritas à mão continuam.
- **Duplicatas:** chunks com texto idêntico (ex.: páginas legadas `--old`) viram um só. **64 removidos**, e os ids descartados ficam no metadado `duplicates`.

## 4. Segmentação (`04_chunk.py`, tokens contados com o tokenizer do BGE-M3)

**Índice base:**

- **Issue/PR:**
  - splitter recursivo com alvo de **700 tokens** (cabeçalho incluído) e **sobreposição de 12%**;
  - separadores em ordem: o separador de comentário `---`, parágrafo, linha, frase, palavra;
  - todo chunk começa com o cabeçalho `[ISSUE #n] título | labels: … | estado: …`, seguido de corpo + comentários.
- **Docs:** corte nos títulos `#`, `##` e `###`; seções com menos de 60 tokens são unidas à seguinte; seções com mais de 800 são subdivididas (12% de sobreposição); o caminho de títulos vai no início do chunk (`[DOC] Título > Seção`).
- **ADR:** mesmo corte, só nas seções principais `##` (Context, Decision, Consequences…), com cabeçalho `[ADR 009] Título > Seção`.
- **Resultado: 39.180 chunks** = 22.207 de issues, 13.692 de PRs, 3.243 de docs e 38 de ADRs.

| Tipo | Média de tokens | Mediana | Máximo |
|---|---|---|---|
| Issue | 551 | 626 | 699 |
| PR | 234 | 149 | 702 |
| Doc | 289 | 219 | 798 |
| ADR | 297 | 228 | 782 |

O sanity check aponta 1 chunk acima do limite (`pr-30391-001`, 702 tokens).

**As 4 variantes do índice** (chunks de `addons_stats.json` e dos `chunks.jsonl`):

| Variante | O que muda em relação ao base | Chunks |
|---|---|---|
| **base** | — | **39.180** |
| **enxuto** (`index_lean`) | issue/PR = só título + primeiro post, **sem comentários e sem cabeçalho**; docs/ADRs iguais ao base (os 3.281 vetores são reaproveitados) | **28.813** (13.271 issue · 12.261 PR · 3.243 doc · 38 ADR) |
| **lógico** (`index_logico`) | corte por unidade lógica: chunk 0 = cabeçalho + título + descrição; depois **comentários inteiros agrupados até 1.000 tokens** (um comentário só é cortado se, sozinho, passar do limite); docs/ADRs com mínimo de 120 tokens por seção. Mesmas fontes e mesmo T | **41.841** (21.304 issue · 17.866 PR · 2.641 doc · 30 ADR) |
| **base + extras** | base + changelogs (217 arquivos → 36.252 chunks) + reviews (11.755 chunks) + commits (20.741 chunks) | **107.928** |

Como as fontes extras foram filtradas:

- **Reviews:** 64.219 comentários brutos de revisão.
  - Removidos: criados ≥ T 5.988; PR não mergeado antes de T 9.681; bots 2.968; baixo valor ou menos de 15 caracteres 3.304.
  - Ficaram 42.278 comentários em 5.749 PRs, agrupados por PR com as últimas 3 linhas do diff.
- **Commits:** 52.191 commits da linha principal (`--first-parent`), agrupados por merge/squash.
  - 20.286 grupos ligados a um PR e 342 sem PR; 280 descartados por serem curtos.
  - Os trailers `Signed-off-by` e `Co-authored-by` são removidos.

## 5. Enriquecimento e transformação

- **Embeddings densos (`05_embed_index.py`):**
  - modelo **BAAI/bge-m3**, **1.024 dimensões**, vetores normalizados, `max_seq_length` 1.024, batch 16, fp16 na GPU;
  - saída: `embeddings.npy` float32 `[39.180 × 1.024]` (conferido) + `ids.json`;
  - rodou no Modal (`modal_app.py`, GPU padrão A10G). Logs:
    - enxuto: 25.532 chunks novos em 163 s numa A10G;
    - lógico: 41.841 em 340 s (o log registra "NVIDIA A10");
    - reviews: 11.755 em 120 s numa A10G.
  - ⚠️ O tempo do índice base ("A10G, ~5 min", do relatório do colega) não está em nenhum log local.
- **Chroma:**
  - coleção persistente com distância **cosseno (HNSW)**, com texto + metadados;
  - nomes: `backstage_chunks` no base e `backstage_chunks_logico` no lógico; o enxuto tem a sua na própria pasta;
  - para a avaliação offline existe uma coleção única `chroma_eval` (ef_search 600).
- **BM25 (`05b_bm25_index.py`):**
  - `bm25s` sobre **os mesmos chunks**: minúsculas, stopwords em inglês, stemmer Snowball English (PyStemmer);
  - variante Lucene, k1 = 1,5, b = 0,75;
  - base: 39.180 chunks e **85.454 termos** no vocabulário.
- **Cabeçalho de contexto:** título, labels e estado dentro de cada chunk de issue/PR. Assim o BM25 e o denso "veem" o título e as labels em todos os pedaços.
- **Descrições de labels (só no nosso backend, usadas no prompt):**
  - `labels.json` tem 76 labels; a triagem usa **42** (`type:`, `area:`, `integration:`, `domain:`, mais `needs:repro` e `needs:more-info`);
  - só 18 delas têm descrição no `labels.json`; o `triage_aids.py` acrescenta 35 descrições de uma linha;
  - resultado: **37 das 42** labels vão com descrição, junto com 3 triagens de exemplo de issues antes de T que não estão no testset (`TRIAGE_LABEL_DESCRIPTIONS=true`).

## 6. Preparação da issue de entrada (nosso backend: `pipeline.triage_once`, `text.clean_issue_body`, `guardrails.cap_input`)

**O que É feito, em ordem:**

1. **Título:** `strip()` e corte em 1.000 caracteres.
2. **Corpo** (`clean_issue_body`):
   - remove comentários HTML `<!-- -->`;
   - remove **toda linha de checkbox desmarcada** (`- [ ] …`);
   - **corta cada bloco de código nas 15 primeiras linhas** e marca o corte com `[... log cortado ...]`;
   - remove títulos (`###`) cuja seção ficou vazia;
   - colapsa linhas em branco repetidas.
3. **Consulta** = `título + "\n" + corpo limpo`, cortada em **20.000 caracteres**. Se cortar, a requisição é marcada com `input_truncated`.
4. **A mesma string vai para o BM25 e para o denso.** Não existe consulta separada por tipo de busca.
   - **BM25:** a consulta é tokenizada igual ao índice (minúsculas, stopwords em inglês, stemmer English). Se o script do time não for importável, usamos o equivalente com PyStemmer, que é o mesmo stemmer.
   - **Denso:** BGE-M3 fp16 na GPU L4, vetor normalizado, sem prefixo de instrução.
   - A reescrita de consulta pelo LLM (`QUERY_REWRITE`) existe, mas está **desligada** por padrão.
5. **Fusão:** RRF ponderado (peso 0,8 para o BM25 e 0,2 para o denso, k = 30). No índice lógico, o top-10 é separado em 6 issues/PRs + 4 docs/ADRs.
6. **Para o LLM** vai o mesmo corpo limpo e cortado.
7. **Labels dos vizinhos:** só de itens anteriores a 22/04/2026 e sem a própria issue (mesmo título).

**O que NÃO é feito com a issue de entrada:**

- **Não mascara `[ref]`.** O mascaramento só existe na montagem do testset (seção 7). Numa issue real colada na demo, os `#1234` e as URLs ficam como estão.
- **Não remove** as seções do formulário com `_No response_` nem as seções de metadados (Code of Conduct, "Issue Labels"). As checkboxes **marcadas** (`- [x]`) ficam.
- **Não remove** linhas de template do `.github`, boilerplate, imagens nem `Signed-off-by`. Essas limpezas existem só no pipeline de dados.
- **Campo "Project Area" sem tratamento especial:** a seção `### 🗃️ Project Area` com a resposta (ex.: "Catalog") fica no texto e entra na busca BM25 e densa como qualquer outra linha. Ela não vira filtro nem dica explícita para o LLM. Aparece em 200 das 216 consultas do testset v2 (as mais comuns: Catalog 47, Core Framework 27, Software Templates 19).
- **Não há** detecção de idioma, tradução nem deduplicação contra o índice. A issue é de depois de T, então não está no índice.
- ⚠️ **Assimetria de tamanho:** no backend, o denso usa o `max_seq_length` padrão do modelo (8.192 tokens, do `sentence_bert_config.json`), enquanto os chunks foram embutidos com 1.024. O efeito disso na qualidade não foi medido.

**Efeito medido no testset v2 (216 consultas):** a limpeza do backend encurtou 56 consultas, cortou logs em 39, e 1 continuou acima de 20.000 caracteres e foi truncada. As consultas do testset já chegam pré-limpas pelo `06_` (seção 7); as issues reais só passam pela limpeza do backend.

## 7. Conjunto de teste (`06_build_testset.py`, `testset_stats.json`)

- **Candidatas:** **468** issues (não PRs) criadas **depois de T** (22/04 a 16/10/2026).
  - Saem **217 de bots** e **4 com primeiro post de menos de 15 palavras** → **247 elegíveis** (86 ainda abertas).
- **Consulta** = título + **primeiro post**, **sem comentários** (a resposta não vaza), com a mesma limpeza da seção 3: HTML, seções de formulário, linhas de template.
- **Mascaramento:** refs do primeiro post que apontam para itens do índice viram **`[ref]`** — `#n`, URLs de issue/PR, ADRs, links para docs.
  - Sem isso, o BM25 casaria "1234" com o cabeçalho `[ISSUE #1234]`.
  - Nas 247: 61 consultas com 150 refs mascaradas; nas 82 com gabarito: 58 consultas e 139 refs.
- **Gabarito de busca** (modo `thread+fix_pr`, confiança ≥ média): **82 issues** com pelo menos 1 documento antigo no gabarito.
  - **142 pares** issue–documento: 68 docs, 58 issues, 16 PRs, **0 ADRs**; 122 documentos únicos.
  - De onde vem o gabarito (uma issue pode ter mais de uma fonte): link no próprio corpo 51 · thread da issue 26 · docs editados pelo PR que a corrigiu 18 · corpo/comentários desse PR 4.
- **Testset v2 = 216** = as 82 + **134 só com gabarito de labels** (têm `area:`).
  - Saíram 14 sem labels type/area nem gabarito e 17 só com `type:` (ainda não triadas).
  - Labels são medidas nas 216; busca e "relacionados", nas 82.
- **Validação:** **129 pares de duplicatas antes de T** ("Duplicate of #B"; 133 encontrados, 4 com corpo curto). Usado só para escolher parâmetros; na busca, a própria issue A é excluída.
- **Depois disso:** v3 (gold automático) e `testset_v4_provisorio` (100 = 82 + 18 anotadas por LLM, **não revisado**).

---

## Versão pra slide

**Slide 1 — Base: Backstage até T = 22/04/2026**
- Fonte: GitHub `backstage/backstage` (API REST + snapshot git de 21/04/2026)
- Índice: **7.381 issues · 12.112 PRs · 424 docs · 15 ADRs** (fev/2020 → abr/2026)
- Corte T evita vazamento: tudo que foi criado depois de T fica fora do índice e vira teste
- Limpeza: bots fora (172 issues, 7.745 PRs, 23.082 comentários) · só PRs **mergeados** antes de T (−2.921) e **com descrição** (−2.385) · "+1"/"thanks" fora (−319)
- Texto: sem HTML, templates, seções vazias de formulário, imagens; changelogs automáticos fora

**Slide 2 — Segmentação e índices**
- Issue/PR: cabeçalho `[ISSUE #n] título | labels | estado` + corpo + comentários, ~700 tokens com 12% de sobreposição
- Docs/ADRs: corte por títulos (60–800 tokens), caminho de seções no chunk
- **39.180 chunks** no base · 4 variantes: enxuto 28.813 (sem comentários) · lógico 41.841 (comentários inteiros) · base + extras 107.928 (changelogs, reviews, commits)
- BGE-M3 (1.024 dimensões, Modal GPU) no Chroma (cosseno) + BM25 (stem em inglês) sobre os mesmos chunks

**Slide 3 — Issue de entrada e teste**
- Entrada: título + corpo limpo (sem HTML, checkbox vazio, logs cortados em 15 linhas, seções vazias), até 20 mil caracteres → mesma consulta no BM25 e no denso → RRF (0,8 BM25)
- Não fazemos: mascarar refs, filtrar por "Project Area" (vai como texto), remover `_No response_`
- Teste: 468 issues depois de T → 247 elegíveis → **82 com gabarito** (142 pares; refs no corpo viram `[ref]`) · v2 com 216 para labels · 129 duplicatas para validação

---

## ⚠️ Não verificado ou com ressalva

1. **"A10G, ~5 min" para os embeddings do índice base** vem só do relatório do colega; não há log local desse passo. Os logs locais são do enxuto (A10G), do lógico ("NVIDIA A10") e dos reviews (A10G).
2. **Contagem bruta de itens:** `clean_stats.json` traz 26.900 PRs e 8.021 issues (deduplicados por id), mas o `sanity_report.json` traz 26.935 e 8.026. A diferença (35 PRs e 5 issues) deve vir da forma de deduplicar (id × número); o motivo exato não foi investigado.
3. **Completude dos reviews:** o estado da coleta de review comments está `done: false` no `_collect_state.json`, mas existe uma coleta paralela por páginas (`_review_pages.json`); não confirmei se foi completa. Isso só afeta a variante base + extras.
4. **Labels e estado** são os atuais, não os de T (limitação do dado, já registrada no pipeline).
5. **Código do backend lido:** `melhorias/work/backend` (a fonte usada nos deploys); não comparei byte a byte com a imagem que está rodando no Modal.
