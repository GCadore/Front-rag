# Prompts utilizados, respostas produzidas e comparação entre versões

> Item 5 do enunciado. Base: código do backend (`backend/rag/prompts.py`, `triage_aids.py`, `query_rewrite.py`, `label_votes.py`, `guardrails.py`, `schemas.py`, `pipeline.py`, `llm.py`) e resultados das baterias (`testes/*.csv`, `raw_busca2.jsonl`, `raw_guardrails.jsonl`, `raw_rag_on_off.jsonl`).
> Legenda: **[medido]** = número tirado das nossas baterias; **[projeto]** = decisão de design, sem medição própria.

---

## 1. Visão geral: quais prompts existem e onde ficam

| Prompt | Para quê | Onde no código | Status |
|---|---|---|---|
| **Triagem: system** (`triage_strict` + `triage_schema`) | Regras e formato JSON da triagem | `rag/prompts.py` → `DEFAULT_PROMPTS` | **em uso** (guardrails ligados) |
| Triagem: system simples (`triage_simple` + `triage_schema`) | Mesma tarefa, sem regras | `rag/prompts.py` | só com guardrails desligados (comparação) |
| **Triagem: user** (5 blocos) | Labels permitidas, exemplos, contexto, labels dos vizinhos, issue nova | `triage_messages()` em `rag/prompts.py`; blocos 2 e 4 vêm de `rag/triage_aids.py` | **em uso** |
| Triagem: correção | Pede o JSON de novo quando a 1ª resposta não valida | `triage_correction()` em `rag/prompts.py` | em uso (no máximo 1 nova tentativa) |
| **Chat RAG** (`chat_strict`) | Responde a perguntas citando trechos `[n]` | `rag/prompts.py` e `backend/prompts/chat_strict.txt` (o texto do arquivo é o mesmo do código) | **em uso** |
| Chat sem RAG (`chat_simple`) | Base de comparação com × sem RAG | `rag/prompts.py` | só no modo `rag=false` |
| Reescrita da consulta (`REWRITE_SYSTEM`) | O LLM resume a issue numa consulta curta para a busca | `rag/query_rewrite.py` | **testado e desligado** (`QUERY_REWRITE=false`) |
| Votação de labels | Usa o **mesmo** prompt da triagem, com 3 amostras a T = 0,7 e labels por maioria | `rag/label_votes.py` | **testado e desligado** (`TRIAGE_LABEL_VOTES=1`) |
| Juiz (avaliação, fora do produto) | Qwen3-30B-A3B dá notas de 1 a 5 (groundedness, utilidade, acionabilidade, suporte das citações) | `testes/judge.py` | só nas baterias |

Os textos podem ser trocados sem mexer no código (`prompts/<nome>.txt` ou a chave `prompts.<nome>` do `config.yaml`). Hoje a pasta `prompts/` só tem `chat_strict.txt`, idêntico ao padrão. Para a triagem vale o texto do código.

**Parâmetros da chamada** (`pipeline.py`, `llm.py`): Qwen3.5-9B (fp8, vLLM no Modal), `temperature = 0.1`, `response_format = json_object` na triagem, `enable_thinking = false` e `max_tokens = 2048`. O chat também usa T = 0,1, com streaming.

---

## 2. Triagem

### 2.1 System prompt (texto literal, modo com guardrails)
```
Você é um assistente de triagem de issues do repositório backstage/backstage.
Use SOMENTE os trechos fornecidos em CONTEXTO, numerados [1]..[k].
Escolha labels SOMENTE da lista LABELS PERMITIDAS. Cite trechos na explicação, assim: [2].
Em related e docs, use apenas números de trechos que existem no CONTEXTO.
Não invente issues, PRs, links, versões ou labels. Escreva a explicação em português.

Responda APENAS com um objeto JSON neste formato, sem texto fora do JSON:
{"labels": [{"name": "string", "confidence": "alta|media|baixa"}],
 "component": "string|null",
 "related": [{"n": 1, "reason": "string"}],
 "docs": [{"n": 3}],
 "needs_more_info": false,
 "explanation": "string com citações [n]"}
```
Sem guardrails, as 5 regras viram uma linha só: "Você ajuda a fazer a triagem de issues do repositório backstage/backstage. Escreva em português." O schema continua o mesmo.

### 2.2 User prompt: os 5 blocos, na ordem de montagem

| # | Bloco | O que contém | Por que existe |
|---|---|---|---|
| 1 | `LABELS PERMITIDAS:` | Uma linha por label de triagem: **42 labels** (`type:*`, `area:*`, `integration:*`, `domain:*`, `needs:repro`, `needs:more-info`), filtradas das 76 do `labels.json`. Cada linha tem uma descrição; quando a do GitHub está vazia, é vaga ("Related to the … project area") ou tem menos de 25 caracteres, entra a nossa, em pt-BR (`LABEL_DESCRIPTIONS`). | Limita o vocabulário (o código remove o que estiver fora) e explica o que cada label significa. **Melhoria B.** |
| 2 | `EXEMPLOS RESOLVIDOS` | 3 triagens de exemplo (few-shot) de issues antigas: scaffolder+GitHub, auth+GitLab, techdocs **sem** integration. Mais 3 regras práticas: exatamente um `type:*`, normalmente uma `area:*`, `integration:*` só quando há um provedor externo específico. | Ensina o formato e o uso de `integration:*`, a família que o modelo mais errava. Só entra junto com B. **Melhoria B.** |
| 3 | `CONTEXTO:` | Os 10 trechos da busca híbrida, numerados `[1]..[10]`, no formato `[n] (issue #123) título - url` + texto do chunk. O cabeçalho do chunk já traz `labels: …` e `estado: …` do item antigo. | É o "R" do RAG: o modelo só pode citar o que está aqui, e o número `n` liga cada citação a um trecho. |
| 4 | `LABELS DAS ISSUES/PRS PARECIDAS` | Até 5 vizinhos (issues/PRs do contexto, na ordem da busca) com os labels `type/area/integration` que os mantenedores aplicaram, mais o aviso "use como referência, não copie sem conferir". A própria issue fica de fora (mesmo título), e também tudo o que foi criado depois do corte T = 22/04/2026. | Few-shot dinâmico: mostra como casos parecidos foram classificados, sem vazar o gabarito. **Melhoria A.** |
| 5 | `ISSUE NOVA:` | `Título:` + corpo limpo (`clean_issue_body`; título + corpo limitados a 20.000 caracteres). | É a entrada a classificar. Fica por último, perto do ponto onde o modelo começa a gerar. |

Se o JSON não valida (Pydantic), o código manda de volta a resposta e "Sua resposta anterior não passou na validação do schema: <erro> … Responda novamente APENAS com o objeto JSON". Se a 2ª tentativa também falha, a triagem sai com erro.

### 2.3 Schema de saída (campos)

| Campo | Significado | O que o código faz com ele |
|---|---|---|
| `labels[].name` | Label sugerida | Só fica se estiver nas 42 permitidas; repetidas são removidas |
| `labels[].confidence` | `alta` / `media` / `baixa` | Normalizado (sem acento, minúsculo); outro valor força a correção |
| `component` | Pacote ou plugin afetado (texto livre) ou `null` | Passa como veio |
| `related[]` | `{n, reason}`: trecho do CONTEXTO que é issue/PR relacionado | `n` tem de estar entre 1 e k; senão, sai. Título, URL, estado e score vêm **dos metadados**, nunca do texto do modelo. Também aceita `id`/`doc_id`. |
| `docs[]` | `{n}`: trecho que é documentação útil | Mesmo filtro por `n` |
| `needs_more_info` | Faltam dados para triar? | Passa como veio |
| `explanation` | Justificativa em pt-BR com citações `[n]` | `[n]` fora de 1..k e menções `#123`/URLs que não estão nos trechos nem na issue são apagadas |

---

## 3. Exemplo real preenchido: #34395

**Issue:** "Bug: `@backstage/integration@2.0.2` causes GitLab requests to fail with 406 Not Acceptable on self-hosted GitLab". **Gabarito:** `type:bug`, `area:techdocs`, `integration:gitlab`; item relacionado #28190.
**Config:** padrão atual (índice base, híbrida RRF w_bm25 0,8 / k 30, sem reranker, guardrails + A + B), resposta `B2-controle-base-q-34395` de `raw_busca2.jsonl`.

### 3.1 Prompt enviado (cortado)
Montado com as próprias funções do backend (`triage_messages`, `neighbor_labels`) sobre os 10 trechos que a busca devolveu, na mesma ordem. Tamanho: system ≈ 0,7 mil caracteres; user ≈ 35 mil (lista de labels 3,2 mil; exemplos 1,4 mil; contexto ≈ 22 mil; vizinhos 0,4 mil; issue 8,0 mil).
```
LABELS PERMITIDAS:
- area:auth: Autenticação e login: providers (GitHub, GitLab, Google, OIDC...), sessões, tokens de usuário, sign-in resolvers.
- area:techdocs: TechDocs: geração/publicação de docs (mkdocs, techdocs-cli), leitor e add-ons.
- integration:gitlab: Envolve GitLab (gitlab.com ou self-hosted: OAuth, provider, publish:gitlab).
- needs:more-info: Issues that need more refinement so that they are easier to pick up
- needs:repro
- type:bug: Algo não funciona como deveria (erro, crash, regressão, comportamento errado).
… (42 linhas)

EXEMPLOS RESOLVIDOS (issues antigas, com os labels que os mantenedores aplicaram):
Exemplo 1 - "[plugin-scaffolder-backend-module-github] customProperties should support a list of strings"
Labels: type:bug, area:scaffolder, integration:github
… (mais 2 exemplos + regras práticas)

CONTEXTO:
[1] (issue #28190) 🐛 Bug Report: GitlabUrlReader not working since undici change - https://github.com/backstage/backstage/issues/28190
[ISSUE #28190] 🐛 Bug Report: GitlabUrlReader not working since undici change | labels: type:bug | estado: closed
… Gitlab responds with `406`. … the `sec-fetch-mode: cors` header is the root cause …
[2] (issue #30079) GitLab URL Reader Confuses Integration and OAuth Tokens, Causing 401s - …
[3] (issue #20753) 🐛 Bug Report: TechDecs Not Working with Privately Self-Signed Self Hosted Gitlab - …
[4] (issue #28190) … (outro chunk da mesma issue)
[5] (issue #25402) … Entity in wildcard subfolder not showing in catalog when fetched from GitLab
[6] (issue #30601) Gitlab: Add retry for fetch requests on 429 responses
[7] (issue #11874) …  [8] (issue #18807) …
[9] (doc-integrations/gitlab/locations) GitLab Locations - …
[10] (doc-integrations/gitlab/org) GitLab Organizational Data - …

LABELS DAS ISSUES/PRS PARECIDAS (labels reais aplicados pelos mantenedores; use como referência, não copie sem conferir se valem para a issue nova):
- [1] issue #28190: type:bug
- [2] issue #30079: type:bug, area:scaffolder, integration:gitlab
- [3] issue #20753: type:bug, area:techdocs
- [5] issue #25402: type:bug, area:catalog
- [6] issue #30601: type:suggestion, area:framework

ISSUE NOVA:
Título: Bug: `@backstage/integration@2.0.2` causes GitLab requests to fail with 406 Not Acceptable on self-hosted GitLab
### 🗃️ Project Area
TechDocs
### 🔗 External Integration
GitLab
### Summary
In `@backstage/integration@2.0.2`, the `fetch` call inside `GitLabIntegration.createFetchStrategy()` had `mode: "same-origin"` removed. On Node 22 … reject with HTTP 406 …
… (diff, script de reprodução, workaround "pin 2.0.1", ambiente: Backstage 1.51.0, Node 22, GitLab self-hosted atrás de nginx)
```
*Os cabeçalhos, a ordem dos trechos e o bloco de vizinhos são os reais. O texto exato de cada chunk não fica salvo no raw, então os trechos acima são do chunk correspondente da base, cortados.*

### 3.2 Resposta do modelo (campos devolvidos; neste caso o guardrail não removeu nada)
```json
{"labels": [{"name": "type:bug", "confidence": "alta"},
            {"name": "area:techdocs", "confidence": "alta"},
            {"name": "integration:gitlab", "confidence": "alta"},
            {"name": "needs:more-info", "confidence": "media"}],
 "component": "@backstage/integration",
 "related": [{"n": 1}, {"n": 3}, {"n": 6}],
 "docs": [{"n": 9}],
 "needs_more_info": true,
 "explanation": "A issue descreve um bug onde a remoção de `mode: 'same-origin'` na versão 2.0.2 de `@backstage/integration` causa erro 406 no GitLab self-hosted devido ao comportamento do `undici` em Node 22 [issue nova]. Isso afeta diretamente o TechDocs e a leitura de árvores de repositório via `GitlabUrlReader` [issue nova, issue #3]. O erro 406 é consistente com o problema relatado na issue #28190, onde o header `sec-fetch-mode: cors` rejeita requisições ao GitLab [issue #28190]. A documentação de integração GitLab [doc #9] confirma que o suporte a self-hosted é esperado, mas a configuração de headers pode variar. Como o problema ocorre especificamente com GitLab self-hosted atrás de nginx e pode depender de configurações de proxy específicas, mais informações sobre a versão do GitLab e do nginx seriam úteis."}
```
(O `reason` de cada related não fica salvo no raw.) Latência: 29,3 s, sendo 28,8 s de LLM e 0,1 s de busca.

### 3.3 O que aconteceu e o que os guardrails fizeram
- **Acertos:** os 3 labels do gabarito (F1 = 1), com o raro `integration:gitlab`. O 1º related é **#28190**, que tem a mesma causa raiz (undici + `sec-fetch-mode`), aberta em dez/2024. O bloco 4 ajudou: os vizinhos [2] e [3] trazem `integration:gitlab` e `area:techdocs`.
- **Guardrails:** os 4 labels estão na lista permitida (`needs:more-info` é permitida). Os `n` 1, 3, 6 e 9 existem, então título e URL foram preenchidos pelos metadados. `removed` ficou vazio: 0 labels, 0 related, 0 docs, 0 citações, 0 menções.
- **Defeitos ligados ao prompt:**
  1. **`needs:more-info` sem necessidade:** a issue traz diagnóstico, diff, script de reprodução, workaround e ambiente, e mesmo assim o modelo pediu "versão do GitLab e do nginx".
  2. **Citações fora do formato `[n]`:** o modelo escreveu `[issue nova]`, `[issue #28190]`, `[doc #9]` e `[issue nova, issue #3]`. O guardrail só reconhece `[n]`, então nada foi conferido: `[issue #3]` não corresponde a nenhuma issue (o trecho 3 é a #20753).
  3. Nas outras configurações, a mesma issue mostra o **related duplicado** (lógico + split: #28190 aparece como n = 1 e n = 5, dois chunks da mesma issue) e um `area:framework` a mais (base + split).

---

## 4. Evolução e comparação entre versões [medido]

| Versão | O que muda no prompt/fluxo | Resultado | Decisão |
|---|---|---|---|
| **Prompt simples × prompt com regras + guardrails** (30 issues reais, índice lógico, 17/10) | `triage_simple` sem filtro × `triage_strict` com filtro no código | F1 dos labels **0,72 → 0,78** (26 issues com gabarito); `needs_more_info` = true em **24/30 → 11/30** | regras + guardrails ligados |
| **v1: prompt base** (blocos 1, 3 e 5) | sem descrições, exemplos nem vizinhos | Base, 82 issues: F1 micro **0,740**; F1 `integration:` **0,444** | substituído |
| + A (vizinhos) | + bloco 4 | F1 0,772; `integration:` 0,471 | — |
| + B (descrições + exemplos) | + descrições no bloco 1 + bloco 2 | F1 0,763; `integration:` 0,545 | — |
| **+ A + B (atual)** | os 5 blocos | F1 **0,780** (Δ +0,041 [−0,003; +0,085]); `integration:` **0,720** (Δ +0,276 [+0,012; +0,567]) | **adotado** |
| + reescrita da consulta | o LLM gera uma consulta curta em inglês, fundida no RRF | Base: ΔF1 0,000 [−0,019; +0,019]; related_hit +4,9 pp [0,0; +11,0]; nDCG +0,001; **+2,3 s** de latência (mediana pareada). Lógico: ΔF1 −0,008 | **desligado** |
| + votação de labels (3 amostras, T = 0,7) | o mesmo prompt 3 vezes; ficam os labels da maioria | Base: ΔF1 −0,009 [−0,034; +0,015]; `integration:` −0,133 [−0,372; +0,044]; **+3,1 s**. 32% dos labels candidatos tiveram só 1 voto em 3 | **desligado** |

**Ressalvas:**
- O IC de +0,041 no F1 geral encosta no zero (P(Δ ≤ 0) = 0,032). O ganho em `integration:` é real, mas **frágil**: são só **13 labels `integration:`** nas 82 issues.
- No índice lógico, B sozinho leva `integration:` de 0,375 a 0,696, mas A sozinho piora o F1 (−0,019).
- Mesmo gabarito de 82 issues em todas as linhas.

**Chat com × sem RAG** (20 perguntas, índice lógico; nota de 1 a 5 dada por um LLM juiz, Qwen3-30B-A3B):

| | sem RAG (`chat_simple`) | com RAG (`chat_strict` + 10 trechos) |
|---|---|---|
| Suporte das citações | **3,00** | **4,95** |
| Groundedness | 4,80 | 4,95 |
| Utilidade | 4,95 | 4,95 |
| Citações por resposta | 0 | 7,0 |
| Tamanho da resposta | 626 palavras | 213 palavras |
| Latência mediana | **56,1 s** | **21,0 s** |

Com RAG a resposta sai mais curta, ancorada e citável, e mais rápida (o modelo gera menos texto). A utilidade percebida pelo juiz é a mesma; o ganho está na verificabilidade.

---

## 5. Decisões de design

- **Guardrails no código, não no prompt [projeto + medido].** O prompt pede "não invente", mas quem garante é o código: schema Pydantic com 1 nova tentativa, lista de labels, `n` entre 1 e k, citações e menções conferidas, metadados de related/docs tirados do índice e recusa por score mínimo. Na busca2 (864 respostas), o código removeu **14 labels fora da lista** (`area:proxy` ×4, `needs:triage` ×4, `area:backend` ×3…), que eram de fato inventadas. Veja na seção 6.2 o que mais ele removeu.
- **Temperatura 0,1 [projeto].** Triagem é classificação, e queremos a mesma resposta para a mesma issue. Só a votação usa 0,7, para as amostras variarem.
- **Só JSON [projeto].** `response_format: json_object` no vLLM + "Responda APENAS com um objeto JSON" + parser tolerante (aceita ```json … ```). O front lê campos, não texto livre. *Thinking* desligado: menos tokens e menos latência.
- **Citações `[n]` [projeto].** Cada trecho tem um número curto e a explicação aponta para ele. Assim o código consegue conferir (o número existe?) e o front transforma em link.
- **Lista fechada de labels [projeto].** 42 labels de triagem com descrição; o que estiver fora é descartado. Os `domain:*` e os `needs:*` entram na lista, mas o gabarito só avalia `type/area/integration`.
- **Few-shot sem vazamento [projeto].** Os vizinhos respeitam o corte T e excluem a própria issue. Dos 3 exemplos fixos, 2 estão na base (#30643, de 2025, e #24452, de 2024, anteriores a T), e nenhum dos 3 está no testset.
- **Issue por último, regras no system [projeto].** As regras ficam no system; o que muda a cada chamada vai no user, terminando na issue nova.

---

## 6. Problemas observados ligados ao prompt [medido] e melhorias futuras

### 6.1 Casos
- **#34022 "Swagger UI deep linking not working": campo "Project Area" ignorado.** Gabarito `area:catalog`; o autor marcou "Project Area: Catalog". Nas 4 configurações o modelo deu `area:openapi-tooling`. O único vizinho com `area:` próxima era #32804 (`area:openapi-tooling`); os outros tinham `area:techdocs` ou nenhuma. Em uma resposta o modelo **leu o campo e mesmo assim** escolheu openapi ("conforme indicado na descrição 'Project Area: Catalog' (que usa OpenAPI)"). O prompt não diz que peso dar ao formulário do autor contra os vizinhos. (É um caso ambíguo: Swagger fica no plugin de API docs.)
- **#34747 "Scaffolder ListTasksPage search only works per page": "citações inventadas" que na verdade eram confusão de numeração.** No base (b), o modelo escreveu `[30542]`, `[32353]`, `[32271]`, o **número da issue**, onde devia escrever o número do trecho. As 3 issues **estavam** no contexto (trechos 1, 4 e 5). O guardrail, que só aceita 1..10, removeu as 3 citações e os 3 related, e a explicação ficou com buracos ("confirmado como um bug conhecido em, onde…").
- **Related duplicado:** em **56 de 864 respostas (6,5%)** a mesma issue aparece duas vezes, porque dois chunks da mesma issue ganham `n` diferentes e a deduplicação é por `n`, não por `doc_id`. O prompt não avisa que trechos diferentes podem ser do mesmo item.
- **`needs:more-info` em excesso:** o label aparece em **157/864 respostas (18,2%)**, e `needs_more_info` = true em 159 (18,4%). Inclui issues muito completas, como a #34395. O gabarito não tem `needs:*`, então não dá para medir acerto, só a frequência. O prompt é confuso aqui: os exemplos do bloco 2 dizem que "needs_more_info pode ser true", o label também está na lista (o mesmo conceito em dois lugares), e a descrição que vai no prompt é a do GitHub, "Issues that need more refinement so that they are easier to pick up", que fala em refinar a issue para quem vai pegá-la, não em faltar dado do autor. O `needs:repro` vai sem descrição.
- **Formato de citação não seguido:** **151/864 respostas (17,5%)** usam outro formato além de `[n]`: `[2, 3]` (85 ocorrências), `[issue nova]` e variantes (≈110), `[issue #N]`. Outras 31 (3,6%) não têm nenhum `[n]`. Esses formatos passam pelo filtro **sem verificação**.
- **Confiança pouco informativa:** dos 2.172 labels, 1.948 vieram "alta", 224 "media" e **0 "baixa"**.

### 6.2 O que os guardrails realmente pegaram (busca2, 864 respostas)
| Removido | Qtde | O que era |
|---|---|---|
| Labels fora da lista | 14 | **invenção real** (`area:proxy`, `needs:triage`, `area:backend`, `integration:cloudflare`…) |
| Related | 94 (em 29 respostas) | **todos** eram o número de uma issue/PR que **estava** no contexto (erro de formato) |
| Citações | 26 (em 11) | 23 eram número de issue presente no contexto; 2 eram `[n]` maior que k; 1 era um número fora das fontes |
| Docs | 2 | número de issue presente no contexto (erro de formato) |
| Menções | 4 | `#10` (provavelmente "trecho 10" escrito como menção; não confirmado) |

Ou seja: a maior parte do que o código removeu **não era alucinação**, e sim o modelo usando o número da issue no lugar do índice do trecho. Na bateria de guardrails, os "22 refs fora das fontes" do modo sem guardrails também não indicam invenção: sem guardrail, o related não é mapeado para `doc_id` e sai vazio (`''`), e o medidor conta cada vazio como "fora das fontes" (22 vazios em 6 issues).

### 6.3 Melhorias futuras (propostas, **não testadas**)
1. **Aceitar o número da issue:** se o modelo escrever `[30542]` e a #30542 estiver no contexto, converter para o `n` dela em vez de apagar. Recuperaria os 94 related e as 23 citações.
2. **Exemplo de citação com o formato exato** no system ("use [3], nunca [issue #123] nem [issue nova]") e normalização de `[2, 3]` → `[2] [3]` antes do filtro.
3. **Deduplicar related por `doc_id`** e agrupar os chunks do mesmo item num único trecho do CONTEXTO.
4. **Regra para o formulário:** "se a issue tem 'Project Area'/'External Integration', use como sinal forte; divirja só com motivo citado".
5. **`needs:more-info` com critério:** tirar da lista (deixar só o campo `needs_more_info`) ou escrever uma descrição própria e exigir que o modelo diga o que falta, citando o template.
6. **Reescrever a explicação** quando uma citação é removida, em vez de deixar buracos.
7. **Confiança útil:** pedir "baixa" quando nenhum vizinho tem o label, ou trocar por uma escala calibrada.

---

## Versão pra slide

**Slide 1: Prompts usados**
- 3 prompts no produto:
  - triagem (system + user em 5 blocos, saída JSON);
  - chat RAG (cita `[n]`);
  - reescrita da consulta (testada, desligada).
- System: "use SOMENTE o CONTEXTO", "labels SOMENTE da lista", "cite [n]", "não invente", JSON fixo.
- User, em ordem:
  1. 42 labels permitidas com descrição;
  2. 3 exemplos resolvidos;
  3. 10 trechos da busca `[1]..[10]`;
  4. labels reais de até 5 vizinhos (antes do corte T);
  5. issue nova.
- Qwen3.5-9B, T = 0,1, JSON forçado, sem thinking; 1 nova tentativa se o JSON não valida.
- Os guardrails ficam **no código**: lista de labels, `n` válido, metadados do índice.
- Exemplo #34395: 3/3 labels certos + #28190 (mesma causa raiz). Defeitos: `needs:more-info` desnecessário e citações `[issue nova]`.

**Slide 2: Versões e o que aprendemos**
- Regras + guardrails × prompt simples: F1 0,72 → 0,78 (30 issues).
- + vizinhos + descrições (A+B): F1 0,74 → **0,78**; `integration:` 0,44 → **0,72** (frágil: 13 labels).
- Reescrita: ΔF1 0,000, +2,3 s · votação ×3: ΔF1 −0,009, +3,1 s → **desligadas**.
- Chat com × sem RAG (20 perguntas): suporte das citações 3,00 → **4,95**; latência 56 s → **21 s**.
- Problemas:
  - "Project Area" ignorado (#34022);
  - número da issue no lugar do `[n]` → guardrail apaga refs legítimas (#34747; 94 related);
  - related duplicado (6,5%);
  - `needs:more-info` em 18%;
  - 17,5% das respostas com citação fora do formato.
- Próximos passos (não testados): mapear nº de issue → `[n]`, dedup por doc, regra para o formulário, `needs:*` com critério.
