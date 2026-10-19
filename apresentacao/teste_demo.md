# Teste dos 4 exemplos da demo (API v16, 18/10/2026, ~18:00 BRT)

**Como foi feito:** `POST /triage` direto na `backstage-rag-api` v16 (Modal), com o mesmo corpo que o front envia (`{title, body, config}`). Título e corpo vêm do `testset_v3.jsonl` (1ª linha = título, resto = corpo). Config = `DEFAULT_CONFIG` do front: `rag: true, index: base, search: hybrid, reranker: false, guardrails: true`. O servidor completou com A+B ligados (`neighbor_labels` e `label_descriptions` = true), `top_k` 10, sem reescrita e sem votação. Para comparar, rodamos 1× com `index: logico` (sem split 6+4, que o front não envia).

**Rodadas:** planejadas 3× padrão + 1× lógico por issue. Por um erro meu, o script rodou de novo, então cada issue tem **6 rodadas no padrão e 2 no lógico** (32 respostas OK). A 1ª chamada, a frio, voltou **HTTP 303 depois de 150 s** (o Modal redireciona requisições longas) e foi refeita.

Gabarito avaliado = só `type/area/integration` (o gabarito completo também tem `stale`/`needs:triage`, que não são previsíveis). Dados brutos: `teste_demo.json`.

| Issue | Esperado | Labels produzidos (padrão, 6×) | Related/docs × gabarito | needs_more_info | Removidos pelo guardrail | Latência (mediana, quente) | Estável? | Pode usar na demo? |
|---|---|---|---|---|---|---|---|---|
| **#34070** Scaffolder + NFS (acerto) | `type:suggestion`, `area:scaffolder`; 5 itens | **6/6 exatos** | **6/6 iguais**: #33439, #32776 + doc `software-templates/configuration` (3 dos 5) | 0/6 | nada | 11,6 s | **sim**: saída idêntica nas 6 | ✅ **sim** |
| **#34395** GitLab 406 (acerto) | `type:bug`, `area:techdocs`, `integration:gitlab`; #28190 | **os 3 certos em 6/6**; exatos em 3/6; extra `needs:more-info` em 3/6 e `area:framework` em 1/6 | **#28190 em 1º lugar em 6/6** | 3/6 | nada | 13,5 s | **acerto estável**; extras variam | ✅ sim, com ressalva (abaixo) |
| **#34022** Swagger (erro) | `type:bug`, **`area:catalog`** | **6/6** `type:bug` + **`area:openapi-tooling`** + `needs:more-info` | **6/6**: #28725 (mesmo bug) em 1º; sem gabarito de itens | 6/6 | nada | 11,0 s | **sim**: erro idêntico nas 6 | ✅ **sim** |
| **#34593** Analytics docs (erro) | **`area:documentation`**; 3 docs + 2 PRs | **6/6** `type:docs` + **`area:design-system`** (1/6 com `needs:more-info`) | **0 hits em 6/6** (traz `releases/v1.49.0`, `versioning-policy`, #24380) | 1/6 | nada | 11,6 s | **sim**: erro idêntico | ✅ **sim** |

**Índice lógico (2×):**
- #34070: igual ao padrão (troca #31251 por #30504; os mesmos 3 hits).
- #34395: labels **exatos** 2/2, mas **#28190 aparece duplicado** no related 2/2.
- #34022: mesmo erro, sem `needs:more-info`; a doc `descriptor-format` sai **repetida** em docs.
- #34593: `type:docs` + `area:core`, ainda errado, 0 hits.

## Observações para a demo
- **#34395:** o acerto principal (os 3 labels + #28190 em 1º) sai sempre. Metade das vezes vem junto um `needs:more-info` desnecessário, e em 1/6 um `area:framework` a mais. Em 5/6 a explicação usa citações fora do formato (`[issue nova]`, `[9, 10]`, `[2, 3]`), e numa rodada do padrão (1/6) o #28190 saiu duplicado. Vale avisar antes ("às vezes acrescenta `needs:more-info`"). Ou use como gancho para falar dos problemas de prompt.
- **#34022:** o erro é estável e bom de mostrar: a busca acerta (#28725, o mesmo bug) e a classificação erra. Nenhuma das 6 explicações menciona "Catalog", embora o formulário diga "Project Area: Catalog".
- **#34593:** erro de **busca** estável: nenhuma das docs certas chega aos trechos.
- **Guardrails:** nenhuma remoção nas 32 respostas. Esses 4 exemplos não mostram o guardrail agindo.
- **Cold start:** a 1ª chamada a frio passou de 150 s e o Modal devolveu **303**. Antes da apresentação, aqueça os containers com uma triagem qualquer, ou use `min_containers=1` no dia. Depois de quente, as respostas levaram ~10–18 s.
- **Reserva, se quiser um acerto "limpo"** (não testado agora, só na busca2): **#34983** "Automatic refresh doesn't work anymore when running techdocs-cli serve command". Na busca2 teve labels exatos (`type:bug`, `area:techdocs`) + item do gabarito nas 4 configurações, sem `needs_more_info`, sem duplicado e sem remoções. Outras opções com o mesmo perfil: #34484 (notifications) e #34274 (scaffolder/OpenTelemetry).

**Recomendação:** os 4 exemplos estão estáveis (os 2 acertos continuam acertos e os 2 erros continuam erros nas 6 rodadas) e podem ficar. Nenhum precisa ser trocado. Se quiser evitar o `needs:more-info` na tela, troque o #34395 pelo #34983, mas aí perde o caso `integration:gitlab`.

## Depois da correção de citações (API v17, 18/10/2026, 18:16–18:17 BRT)

**O que mudou** (edição do Claude, deploy v17 às 18:13 BRT):
- `normalize_citations` reescreve `[issue #N]`, `[#N]`, `[doc-…]`, `[1, 3]` e `[issue nova]` para `[n]` / "(issue nova)" antes dos guardrails;
- o prompt da triagem e o do chat ganharam a regra "cite SOMENTE `[n]`… nunca `[issue #123]` nem `[issue nova]`";
- related e docs passaram a ser deduplicados por `doc_id`.

Testes: **98 passed**. O resto do backend é o mesmo da v16: split por índice, related_cut, reescrita, votação e settings não mudaram.

**Como rodou:** 1 chamada de aquecimento (#34983, fora da demo; 110 s, cold start do LLM) e depois **1 chamada por exemplo**, em sequência, com o mesmo corpo do front. Nenhuma falha, nenhum 303, nenhuma repetição.

| Issue | Labels (v17) × gabarito | Related/docs × gabarito | needs_more_info | Citações na explicação | Removidos | Latência | Bate com o resultado estável anterior? |
|---|---|---|---|---|---|---|---|
| #34070 (acerto) | `type:suggestion`, `area:scaffolder`: **exatos** | #33439, #32776, #31251, #32574 + doc `configuration`; **3 hits** (iguais aos de antes) | não | `[1] [2] [3] [5] [1] [7]`: **todas `[n]`** | nada | 11,2 s | **sim**, idêntico |
| #34395 (acerto) | os 3 certos + **`area:framework`** a mais (antes 1/6); sem `needs:more-info` | **#28190 em 1º**, #20753, #30601 (**sem duplicata**) | não | `[1] [3] [1] [4] [6] [9]`: **todas `[n]`**; "(issue nova)" ×2 em texto | nada | 15,8 s | **sim**, o acerto continua |
| #34022 (erro) | `type:bug` + **`area:openapi-tooling`** (esperado `area:catalog`) | #28725 em 1º, #32804, #9345; sem gabarito de itens | **não** (antes 6/6 sim) | `[1] [1] [2] [5]`: **todas `[n]`** | nada | 8,6 s | **sim**, o mesmo erro |
| #34593 (erro) | `type:docs` + **`area:design-system`** + `needs:more-info` (esperado `area:documentation`) | `releases/v1.49.0`, `versioning-policy`, `releases/v1.40.0`; **0 hits** | sim (antes 1/6) | `[2] [6] [10]`: **todas `[n]`** | nada | 11,4 s | **sim**, o mesmo erro |

**Conclusões:**
- **Formato das citações resolvido nos 4:** 0 citações fora de `[n]` e 0 remoções. Antes, o #34395 tinha `[issue nova]`/`[9, 10]` em 5 de 6 rodadas. A API não informa se o modelo já obedeceu à regra ou se o código normalizou, então não dá para separar os dois efeitos.
- **Resta um defeito no texto corrido (fora dos colchetes):** o modelo escreve "**A issue #3** também relata…" (#34395) e "**A issue #5** também menciona…" (#34022), usando o número do trecho como se fosse o da issue. O trecho 3 é a #20753 e o 5 é a #9345. A normalização não pega isso, porque não está entre colchetes, e o filtro de menções também deixou passar. Na demo, se alguém perguntar, explique que é o trecho 3/5.
- Também não coberto: um número cru de issue entre colchetes, como `[30542]` (o caso do #34747), continua sendo tratado como `n` inválido e removido.
- Os 4 exemplos continuam seguros para a demo; os resultados batem com os da v16.

## Depois da correção do texto corrido (API v18, 18/10/2026, 19:00–19:03 BRT)

**O que mudou** (edição do Claude, deploy v18 às 19:00 BRT): `fix_index_mentions` troca "issue #K" no texto corrido, quando K é o número de um trecho (1..k), pela referência real do trecho: "issue #20753", "PR #…" ou, para docs, `doc “título” [k]`. Fica como está quando K é o número real de algum trecho ou aparece no texto do usuário. Funciona na triagem, no /chat e no streaming.

Testes: **103 passed**. Backup da v17 verificado antes da troca: `backend_v17_20261018-1859.zip`, 36 arquivos.

**Como rodou:** /health (64 s, cold start da API), 1 aquecimento (#34983, 83 s) e **1 chamada do #34395** com o `DEFAULT_CONFIG` do front. Nenhum 303, nenhuma repetição.

| #34395 (v18) | Resultado |
|---|---|
| Labels | `type:bug`, `area:techdocs`, `integration:gitlab` (os 3 do gabarito) + `area:framework` a mais (também saiu na v17 e em 1/6 da v16); sem `needs:more-info` |
| Related | **#28190 em 1º**, #30079, #20753, #30601; sem duplicata |
| Docs | `integration/gitlab/locations` |
| Citações | `[1] [3] [1] [6] [2] [9]`: **todas `[n]`**, nenhuma removida |
| Texto corrido | **nesta rodada o modelo não escreveu nenhum "issue #K"** (só "a issue nova" e citações `[n]`), então a correção não teve o que trocar |
| Latência | 13,6 s (servidor), 14,2 s (cliente) |

**Prova da correção nos textos reais da v17** (feita offline, sem custo): apliquei a função da v18 às explicações que a v17 gerou, usando os trechos daquela resposta.
- #34395: "A issue **#3** também relata…" → "A issue **#20753** também relata…"; "A issue **#6** trata…" → "A issue **#30601** trata…"; a "issue #28190", que é o número real, não mudou.
- #34022: "A issue **#5** também menciona…" → "A issue **#9345**…"; "#28725" não mudou.

**Conclusão:** a v18 mantém o acerto do #34395 (labels e #28190) e o formato `[n]`. A correção do texto corrido funciona nos casos reais em que o erro apareceu. Nesta chamada ao vivo o modelo não cometeu o erro, então ao vivo ela não foi exercitada.
