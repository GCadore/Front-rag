# Análise crítica: justificativa das técnicas, exemplos de erro e acerto, limitações e riscos

Itens 4, 5 e 6 do enunciado. Legenda: **[medido]** = número tirado das nossas planilhas e saídas; **[projeto]** = justificativa de desenho, sem medição própria; **[colega]** = relatório do colega (`/workspace/colega`).

Fontes conferidas em 18/10/2026:
- `testes/Resumo.csv` (1ª bateria, 82 issues, 12 configs);
- `testes/Busca*.csv` (varredura do RRF);
- `testes/Melhorias*.csv` (A/B);
- `testes/Decisao_busca_*.csv`;
- `testes/RV_*.csv` (reescrita e votação);
- `testes/B2_*.csv` + `testes/raw_busca2.jsonl` (216 issues × 4 configs = 864 respostas);
- `gold_v4/V4_*.csv` (gabarito v4 provisório);
- `testes/bateria_rerank_blend.xlsx`;
- `testes/Resumo_outros.csv` (guardrails, chat com/sem RAG, partida a frio);
- código em `melhorias/work/` (backend, front, `modal/llm_qwen.py`).

Salvo indicação, IC95 = bootstrap pareado.

---

## Parte 1 — Justificativa das técnicas

| Técnica | Por que escolhemos | Evidência |
|---|---|---|
| **RAG para triagem** | O problema é **memória de projeto**: a resposta útil está em issues, PRs e docs antigos. Fine-tuning não cita fonte e envelhece; RAG cita ids reais e atualiza só reindexando. | **[colega]** Com × sem RAG (247 issues): acertar ≥1 doc do gabarito 0% → 31,7% (IC +22,0 a +42,7 pp); citações que existem no índice 3,1% → 90,5%; acerto de área 84,3% → 85,4% (n.s.). **[medido]** No nosso chat (20 perguntas): suporte das citações (juiz LLM) 3,00 → 4,95; latência mediana 56,1 s → 21,0 s. **Para a triagem, a comparação com × sem RAG é só a do colega.** |
| **BGE-M3** (denso) | **[projeto]** Modelo aberto, multilíngue (issues em inglês, perguntas em pt-BR no chat), 1.024 dimensões, aceita textos longos (até 8.192 tokens; nos chunks usamos 1.024). | **[medido]** Sozinho é o pior em ranking (nDCG@10 0,386 contra 0,428 do BM25), mas tem o melhor F1 de `integration:` (0,556 contra 0,333 do híbrido), o que justifica mantê-lo na fusão. |
| **Chroma** | **[projeto]** Banco vetorial embutido (arquivo, sem servidor), HNSW com cosseno e metadados para filtrar por tipo e data. Cabe num Modal Volume e sobe junto com a API. | Não comparamos com outros bancos. |
| **BM25** | **[projeto]** Issues têm muitos identificadores exatos (`@backstage/integration`, `RepoUrlPicker`, `publish:github`, mensagens de erro) que o denso "borra". | **[medido]** BM25 sozinho supera o denso: nDCG@10 0,428 × 0,386; Recall@10 0,559 × 0,526 (1ª bateria, base). |
| **Híbrida RRF com w_bm25 = 0,8, k = 30** | Junta os dois sinais; o peso alto no BM25 reflete o ponto acima. | **[medido]** Varredura offline (base, 82 issues): RRF antigo (w 0,5, k 60) nDCG 0,439 / Recall@10 0,548 → **w 0,8, k 30: 0,471 / 0,589**. Δ nDCG +0,032 [−0,002; +0,068], P(Δ ≤ 0) = 0,024, 22 consultas melhores e 12 piores. Na média dos índices, ficou entre as melhores das 33 variantes (0,471); a versão agrupada por documento deu 0,474, mas não melhorou a triagem. |
| **Reranker removido do padrão** | O bge-reranker-v2-m3 é a escolha "de livro", mas aqui piorou. | **[medido]** 1ª bateria: base híbrida nDCG 0,439 → **0,324** com reranker; lógico 0,457 → 0,335. Bateria offline de 18/10: reranker **puro** 0,35 contra 0,47 do 1º estágio; **blend** (RRF 2:1, 3:1) neutro, Δ nDCG entre −0,022 e +0,016, sempre com IC cruzando zero. A ordem do 1º estágio já separa gold de não-gold melhor (AUC 0,86–0,88) que o reranker (0,80–0,82). O reranker **continua disponível** (`reranker: true`) e custaria ~0,3–0,5 s por consulta na L4. |
| **Índice lógico** (comentários inteiros por chunk) | Comentário cortado no meio perde contexto; o lógico agrupa comentários inteiros. | **[medido]** 1ª bateria (híbrida, sem reranker): **lógico nDCG 0,457 / Recall@10 0,583** × base 0,439 / 0,548 × base+extras 0,427 / 0,553 × enxuto 0,420 / 0,548. ICs largos e sobrepostos ([0,375; 0,540] × [0,359; 0,523]). Com a busca nova (b), lógico e base empatam (0,471 nas 82). A vantagem do lógico aparece com o split (próxima linha). ⚠️ No front, o índice padrão continua **base** (`DEFAULT_CONFIG.index = "base"`); o lógico é a opção com o melhor número medido. |
| **Split 6 issues/PRs + 4 docs no lógico** | Docs e ADRs perdiam espaço para issues no top-10. | **[medido]** Offline (v4, 82 issues): nDCG 0,471 → 0,490, **Δ +0,019 [+0,001; +0,038]**; Recall@10 0,569 → 0,615. Ponta a ponta, pelo front (busca2): Δ nDCG das fontes +0,022 [+0,004; +0,045]; related_hit 59,8% → 65,9% (+6,1 pp [−1,2; +14,6]); F1 de labels igual (+0,002). No **base** não vale: Δ nDCG +0,016 [−0,006; +0,038] e F1 `integration:` −0,054. **Ganho pequeno e consistente, mas sempre medido no mesmo conjunto de 82 issues.** |
| **A = labels dos vizinhos + B = descrições dos labels** | O modelo errava labels raros (`integration:*`) por não saber o que significam. | **[medido]** Base, 82 issues: F1 micro 0,740 → **0,780** (Δ +0,041 [−0,003; +0,085]); F1 `integration:` **0,444 → 0,720** (Δ +0,276 [+0,012; +0,567]). No lógico, B sozinho já leva `integration:` de 0,375 a 0,696, e o F1 micro fica igual (+0,007). ⚠️ O F1 de `integration:` se apoia em só **13 labels** nas 82 issues. |
| **Qwen3.5-9B, fp8, vLLM no Modal** | **[projeto]** Modelo aberto (sem API paga, dados não saem do nosso ambiente). Com fp8 os pesos ficam em ~10 GB e cabem numa A10G de 24 GB com 32k de contexto; em bf16 deu OOM (`llm_qwen.py`). O vLLM expõe API compatível com a da OpenAI com saída JSON. Scale-to-zero (`min_containers = 0`): custo zero parado. | **[medido]** Mediana de 22,5 s por triagem (864 respostas, p90 29,9 s). O Modal (billing medido) foi de US$ 5,01 a US$ 20,64 em todas as baterias (17–18/10), ≈ US$ 15,6 de créditos. |
| **Guardrails no código, não no prompt** | **[projeto]** Pedir no prompt "não invente" não garante nada; o código checa depois: valida o schema JSON (com nova tentativa), remove labels fora da lista, citações e related/docs que não estão nas fontes entregues, menções `#n`/URLs desconhecidas, e recusa quando o score é baixo. | **[medido]** 30 issues reais: refs fora das fontes 22 → **0**; F1 0,72 → 0,78. Chat fora do tema: 95% de recusa com guardrails × 0% sem. |
| **Reescrita da consulta e votação de labels: testadas e desligadas** | Ideias comuns para melhorar a busca e a estabilidade dos labels. | **[medido]** Reescrita (base): F1 igual (Δ 0,000 [−0,019; +0,019]), related_hit +4,9 pp [0,0; +11,0], nDCG +0,001, **+2,3 s** de latência; no lógico, F1 −0,008. Votação com 3 amostras: F1 −0,009, `integration:` −0,133 [−0,372; +0,044], **+3,1 s**. Custo sem ganho → desligadas (podem ser ligadas por requisição). |
| **Corte temporal T = 22/04/2026** | Evitar vazamento: a issue de teste, os comentários dela e o PR que a corrigiu não podem estar no índice. | **[medido]** 0 chunks com data ≥ T. As labels dos vizinhos também respeitam T (`TRIAGE_NEIGHBOR_CUTOFF`). Refs do corpo da issue de teste mascaradas como `[ref]` (139 refs em 58 das 82). |

---

## Parte 2 — Exemplos de erro e acerto (saídas reais de `raw_busca2.jsonl`, via `/triage`)

As duas configurações padrão são **base (b)** e **lógico + split**. O "gabarito" é o automático (labels atuais e documentos ligados).

### ✅ Acerto 1: #34070 "Allow More Flexible Scaffolder Customization Using the New Frontend System"
- **Esperado:** `area:scaffolder` e `type:suggestion`. Itens: #32776, #33206, #33439, #33749 e a doc "Software Template Configuration".
- **Produzido** (iguais nas duas configs):
  - labels `type:suggestion` e `area:scaffolder`;
  - related #33439, #32776, #31251 (lógico: #30504), #32574;
  - doc `software-templates/configuration`.
- **Por quê:** labels exatos e 3 dos 5 itens do gabarito. #33439 e #32776 estavam **mascarados como `[ref]`** no texto: o RAG reencontrou o histórico que o autor citava.

### ✅ Acerto 2: #34395 "`@backstage/integration@2.0.2` causes GitLab requests to fail with 406"
- **Esperado:** `type:bug`, `area:techdocs`, `integration:gitlab`; item #28190.
- **Produzido:**
  - lógico + split: os 3 labels certos; related #28190, #20753, **#28190 (duplicado)**;
  - base (b): mesmos labels **+ `needs:more-info`** (não pedido).
- **Por quê:** acerta o label raro `integration:gitlab` (só 22 issues da base o têm). O 1º relacionado é exatamente a issue de dezembro de 2024 com a mesma causa raiz (undici + `sec-fetch-mode`): é a "memória de projeto". Mostra também dois defeitos, o related duplicado e o `needs:more-info` em excesso.

### ✅ Acerto 3: #35727 "TechDocs addons do not appear on the TechDocs reader page in v1.55.0"
- **Esperado:** `type:bug`, `area:techdocs`; doc `techdocs/addons`.
- **Produzido:**
  - base (b): labels exatos; doc `techdocs/addons` (do gabarito) + `getting-started`;
  - lógico + split: os mesmos docs, mas **acrescentou `area:framework` e `needs:more-info`**.
- **Por quê:** a busca trouxe a doc certa em 1º lugar e o modelo a usou. No lógico, a explicação tem citação repetida ("[6] [6]", "[1] [1]"), um defeito cosmético.

### ❌ Erro 1: #34022 "Swagger UI deep linking not working" (label errado, busca certa)
- **Esperado:** `area:catalog`, `type:bug` (sem itens de gabarito).
- **Produzido** (nas duas configs): `type:bug` + **`area:openapi-tooling`**; related #28725 "Swagger deep linking broken after upgrading to 1.35".
- **Por quê: erro do LLM, com gabarito ambíguo.** O Swagger fica no plugin de API docs, então `openapi-tooling` é plausível. Mas os mantenedores usaram `area:catalog`, e o autor marcou "Project Area: Catalog" no formulário. O modelo não aproveitou esse campo. A busca acertou: trouxe a issue antiga com o mesmo bug.

### ❌ Erro 2: #34747 "Scaffolder ListTasksPage search only works per page" (citação inventada + área faltando)
- **Esperado:** `type:bug`, `area:scaffolder`, **`area:search`**.
- **Produzido** (base (b)): `type:bug`, `area:scaffolder`. O modelo citou #30542, #32353 e #32271, que **não estavam nos trechos entregues**. O guardrail removeu as 3 citações e os 3 related, e related ficou vazio.
- **Por quê: alucinação do LLM, barrada pelo código.** O defeito é a explicação: "Isso é confirmado como um bug conhecido em, onde a busca não aparece… também é relatado em e, que discutem…". A frase fica com buracos. No lógico + split, as mesmas 3 issues **vieram na busca** e foram aceitas como related legítimas. Ou seja, o modelo "lembrava" delas, mas a busca do base não as trouxe. Faltou também `area:search`, um caso de várias áreas (20 das 216 issues têm mais de uma `area:`).

### ❌ Erro 3: #34593 "Not documented changes regarding Analytics plugin API" (busca falhou)
- **Esperado:** `area:documentation`. Itens: docs `building-plugins/08-analytics`, `plugins/analytics`, `building-apps/08-migrating` (+ 2 PRs).
- **Produzido:**
  - base (b): **`type:docs` + `area:design-system`**; related `releases/v1.49.0`, `versioning-policy`, #24380;
  - lógico + split: `type:docs` + `area:core`.
- **Por quê: falha de recuperação, que derrubou a classificação.** Nenhum documento do gabarito veio nas fontes (só notas de versão, que batem por palavras como "changes" e "API"). Sem a doc de analytics, o modelo chutou a área e justificou com trechos irrelevantes.

### Padrões observados (864 respostas da busca2)
- **A busca é o gargalo dos "relacionados".** Nas 82 issues com gabarito (base (b)):
  - 50 acertam (gold em related ou docs);
  - em **26 a busca não trouxe nenhum gold**;
  - em só 6 a busca trouxe o gold e o LLM não escolheu.
  - No lógico + split: 54 acertos / 21 falhas de busca / 7 de escolha.
- **Precisão dos relacionados ~22%:** de 259 related únicos sugeridos, 58 estão no gabarito. Parte disso é gabarito incompleto: o automático só conhece links explícitos.
- **Labels: `area:` é a família mais difícil.** F1 de `type:` 0,818, `area:` 0,772, `integration:` 0,750 (base (b), 216 issues). Erros típicos:
  - áreas vizinhas (catalog × openapi-tooling, framework × core);
  - várias áreas na mesma issue;
  - `area:documentation` × `type:docs`.
- **`needs:more-info` em excesso:** marcado em **159 de 864** respostas (18%), quase sempre ausente no gabarito.
- **Docs legados duplicados ocupam espaço no contexto:** páginas `--old` (ex.: `techdocs/addons--old`) vêm junto com a nova, e o dedupe só remove texto idêntico.
- **Defeitos de saída:**
  - related com item repetido em **56 de 864** respostas (6,5%), como o #28190;
  - explicação com buracos quando o guardrail remove a citação;
  - citações repetidas ("[6] [6]").

---

## Parte 3 — Limitações e riscos

### Limitações medidas
1. **Recuperação é o gargalo.**
   - Recall@10 ≈ 0,59 (base (b)) a 0,62 (lógico + split) nas 82 issues.
   - O teto dos 50 primeiros candidatos é 0,74–0,80: os gold existem no índice, mas não chegam ao top-10.
   - Related: precisão ~20% (0,21–0,22) e related_hit ~60–66%.
2. **Gabarito pequeno e aproximado.**
   - Só 82 issues com gabarito de busca (142 pares; 0 ADRs). A maioria dos ICs cruza zero.
   - Ruído entre rodadas da mesma config: related_hit 65,9% × 61,0% no lógico (~5 pp); F1 0,780 × 0,793 no base.
   - O v4 provisório (100 = 82 + 18 anotadas por LLM, **não revisado**) é otimista: nas 18 novas, nDCG 0,63 × 0,47 nas 82, por viés de pooling (só foi julgado o que o sistema trouxe).
   - A avaliação humana (`Avaliacao_Humana.csv`, 20 itens) **não foi preenchida**.
   - O juiz LLM saturou (notas ~4,9 de 5) e é da mesma família do modelo avaliado.
3. **Labels "de hoje", não de T:** o gabarito usa labels atuais. 280 issues e 1.528 PRs foram editados depois de T. Alguns erros de label são, na verdade, ambiguidade do gabarito (#34022).
4. **Entrada da triagem menos limpa que a base:**
   - em produção não mascaramos `[ref]`;
   - não removemos as seções `_No response_` nem as metadados do formulário.
   - O campo **"Project Area"** vai como texto puro: 200 das 216 consultas o têm. É ao mesmo tempo um sinal útil e um **vazamento de rótulo** a favor do modelo (o autor já sugere a área), e o modelo nem sempre o segue (#34022).
5. **Assimetria do denso:** os chunks foram embutidos com até 1.024 tokens, mas a consulta pode chegar a 8.192 (padrão do modelo na API). O efeito não foi medido.
6. **Sem comparação com × sem RAG da nossa triagem:** só a do colega (dele, área 84,3% × 85,4%, n.s.). A nossa é do chat (20 perguntas).
7. **Testset com issues quase repetidas:** #34625, #34626 e #34627 têm o mesmo título ("Remove ESM transform workarounds once Node 22 is dropped") e pesam 3 vezes.

### Riscos, falhas e alucinações observadas
- **Alucinação de referências:**
  - sem guardrails, 22 refs fora das fontes em 30 issues;
  - na busca2 (864 respostas), o código removeu: **related em 29 respostas (94 itens)**, citações em 11 (26), labels fora da lista em 14 (14: `area:proxy` ×4, `needs:triage` ×4, `area:backend` ×3…), menções em 4, docs em 2.
  - Resultado final: **0 labels alucinados e 0 refs fora das fontes**.
- **Remoção deixa texto quebrado** (#34747): o risco passa de "inventar" para "explicação incompleta".
- **Bug de related duplicado** em 6,5% das respostas.
- **Riscos do colega [colega]:**
  - com o JSON schema forçado no vLLM, **44 respostas com RAG (18%)** entraram em loop de espaços até o limite de tokens; 33 tiveram de ser refeitas sem schema;
  - sem RAG, **74 citações eram `issue-1234`**, o exemplo escrito no prompt, copiado como se fosse fonte;
  - o front usa Next 15.3.3, com alerta de segurança (**CVE-2025-66478**): atualizar antes de publicar.
- **Custo e partida a frio:**
  - scale-to-zero zera o custo parado, mas a 1ª chamada é lenta: API ~53 s para responder ao health; 1º token do LLM ~81 s;
  - GPU ligada custa (LLM em A10G; o colega estima ~US$ 1,10/h);
  - houve um outlier de 327 s numa triagem e HTTP 502 na 1ª tentativa de algumas baterias (refeitas com sucesso).

### Melhorias futuras
- **Gabarito:** revisar à mão as 30 issues pré-anotadas (pooling) e preencher a avaliação humana dos 20 itens.
- **Busca:** testar consulta separada para o BM25 (título + identificadores), deduplicar as páginas `--old`, usar o "Project Area" como dica explícita (ou testar sem ele, para medir o vazamento) e embutir a consulta com 1.024 tokens, igual aos chunks.
- **Saída:**
  - deduplicar related, docs e citações;
  - quando o guardrail remover uma citação, reescrever a frase;
  - calibrar `needs:more-info`;
  - placeholder no prompt que não pareça um id (lição do `issue-1234`).
- **Experimento com × sem RAG da nossa triagem** (o mesmo conjunto de 216 issues).
- **Operação:** atualizar o Next.js; aquecer containers antes da demo (com autorização de custo).

---

## Versão pra slide (4 slides)

**Slide A — Por que cada técnica (medido)**
- RAG: com × sem, acerto ≥1 doc 0% → 32%; citações reais 3% → 90% (colega)
- BM25 > denso (nDCG 0,43 × 0,39): identificadores exatos → híbrida RRF w_bm25 0,8 / k 30: nDCG 0,44 → **0,47**
- Reranker piorou: nDCG 0,44 → 0,32; o blend é neutro → desligado
- Prompt A+B (vizinhos + descrições): F1 0,74 → **0,78**; `integration:` 0,44 → **0,72**
- Lógico + split 6+4: nDCG +0,019 [+0,001; +0,038]: ganho pequeno e consistente no mesmo conjunto de 82
- Reescrita e votação: sem ganho, +2–3 s → desligadas

**Slide B — Por que cada técnica (projeto)**
- BGE-M3: aberto, multilíngue, textos longos · Chroma: embutido, sem servidor, filtro por metadado
- Qwen3.5-9B fp8 no vLLM/Modal: modelo aberto, cabe em 24 GB, JSON, scale-to-zero (~US$ 15,6 em todos os testes)
- Guardrails no código: refs fora das fontes 22 → 0; recusa fora do tema 95%
- Corte T = 22/04/2026 + `[ref]`: sem vazamento da resposta

**Slide C — Acertos e erros**
- ✅ #34070: labels exatos + 2 issues que o autor citava (mascaradas) reencontradas
- ✅ #34395: `integration:gitlab` + mesma causa raiz em #28190 (dez/2024)
- ❌ #34022: `openapi-tooling` × `catalog`: busca certa, LLM errou (e ignorou "Project Area")
- ❌ #34747: inventou 3 citações → guardrail removeu, mas a frase ficou com buracos
- ❌ #34593: busca não trouxe a doc de analytics → área chutada
- Padrão: nas falhas de related, 26 de 32 vêm da **busca**, não do LLM; `area:` é a família mais difícil

**Slide D — Limitações, riscos e próximos passos**
- Recall@10 ~0,6 e precisão de related ~20%: a recuperação é o gargalo
- Gabarito pequeno (82), ruído de ~5 pp entre rodadas, labels de hoje; o v4 provisório é otimista
- Alucinações barradas: 94 related + 26 citações + 14 labels removidos em 864 respostas · related duplicado em 6,5%
- Entrada sem `[ref]` e "Project Area" como texto · denso 8.192 × 1.024 · cold start de ~1 min · loop de JSON (colega, 18%) · CVE do Next
- Próximos: anotação humana, consulta própria para o BM25, dedupe de saída, triagem com × sem RAG
