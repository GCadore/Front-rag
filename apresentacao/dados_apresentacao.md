# Dados para o seminário (15 min): o que usar em cada seção

Todos os números são reais e vêm de `estatisticas_base.json`, `exemplos_demo.md` e `relatorio_melhorias.docx` (que tem os intervalos de confiança).

**1. Retomada do problema**
- Projetos perdem contexto: decisões passadas e issues que já foram resolvidas.
- Proposta: triagem de issues novas com RAG + LLM sobre o histórico do backstage/backstage (~34,5 mil estrelas, ~7,6 mil forks, 15 ADRs).
- Perguntas de pesquisa P1/P2 e hipóteses H1/H2: ver a proposta.

**2. Base e preparação** (`grafico2_issues_por_mes.png`, `grafico4_mix_tipos.png`, `grafico3_chunks_por_indice.png`)
- **Base indexada:** 19.932 documentos.
  - 7.381 issues (09/02/2020 a 20/04/2026)
  - 12.112 PRs (03/02/2020 a 20/04/2026)
  - 424 páginas de docs
  - 15 ADRs
- **Corte temporal:** T = 22/04/2026. Tudo o que é posterior fica fora do índice e serve de teste, para não vazar resposta.
- **Limpeza** (dados brutos: 8.021 issues, 26.900 PRs, 104.105 comentários):
  - Issues: −172 escritas por bots e −468 posteriores a T.
  - PRs: −7.745 de bots, −2.921 não mergeadas antes de T, −2.385 sem descrição e −1.737 posteriores a T.
  - Comentários: −23.082 de bots e −319 de baixo valor; ficaram 50.980.
  - Docs: −222 changelogs e −3 vazias.
  - Também foram removidas as linhas de template, como "- [x] i checked and didn't find similar issue".
- **Tamanho mediano (palavras):** issue 366 (p10 106; p90 1.128), PR 58, doc 664, ADR 345.
- **Chunks por índice:** base 39.180, enxuto 28.813, lógico 41.841, base+extras 107.928 (este inclui 36.252 de changelogs, 20.741 de commits e 11.755 de reviews). Verificação: 0 chunks duplicados.
- **Labels** (`grafico1_top15_labels.png`):
  - 6.994 das 7.381 issues têm labels.
  - Mais comuns: type:bug 3.767, type:suggestion 2.319, area:catalog 906, area:scaffolder 631, area:techdocs 586.
  - integration:* é raro: github 25, azure 23, gitlab 22.
- **Conjunto de teste:**
  - 468 issues posteriores a T. Saíram 217 de bots e 4 com corpo curto, sobrando 247 elegíveis.
  - **82 têm gabarito de busca**, com 142 referências (122 únicas: 54 issues, 52 docs, 16 PRs; 1,73 por issue).
  - As referências do próprio texto foram mascaradas como `[ref]`: 150 refs em 61 issues.
  - Testset v2: **216 issues** = as 82 + 134 só com gabarito de labels.

**3. Solução implementada** (`arquitetura.png`, fonte em `arquitetura.mmd`)
- Front em Next.js → backend FastAPI no Modal (GPU L4) → Qwen3.5-9B com vLLM no Modal (GPU A10G, fp8).
- Os índices Chroma ficam num Modal Volume.
- Scale-to-zero: o custo é zero quando ninguém está usando.

**4. Técnicas utilizadas**
- Embeddings BGE-M3 + BM25, combinados por RRF (peso do BM25 0,8; k = 30).
- Chunking por variante (base / enxuto / lógico).
- No índice lógico, busca separada: 6 issues/PRs + 4 docs.
- No prompt (`prompts.md`):
  - A = labels reais das issues vizinhas;
  - B = descrições dos labels + 3 exemplos resolvidos.
- Guardrails: o schema JSON é validado e são removidos labels fora da lista e citações que não estão no contexto.
- Avaliação: Recall@10, MRR, nDCG@10, F1 de labels, related_hit e bootstrap pareado (IC95).

**5. Demonstração** (`exemplos_demo.md`)
- Sucessos:
  - #34070 (Scaffolder/NFS): labels exatos e 2 issues relacionadas que estavam mascaradas.
  - #34395 (GitLab 406): 3 labels certos, incluindo integration:gitlab, e a mesma causa raiz encontrada em #28190.
- Erros:
  - #34022: área errada (openapi-tooling no lugar de catalog), mas a busca acertou.
  - #34747: o modelo citou pelo número da issue em vez do `[n]` do trecho, e os guardrails apagaram 3 referências que estavam no contexto.
- Também mostrar o prompt, a resposta em JSON e a comparação entre versões (tabela abaixo).

**6. Resultados** (`resultados_fig1_f1_labels.png`, `resultados_fig2_busca.png`)

Evolução no índice base. As linhas até a votação usam 82 issues; as duas últimas usam o testset v2 (labels sobre 216 issues, busca sobre 82).

| Etapa | F1 labels | F1 integration: | nDCG@10 | MRR | Decisão |
|---|---|---|---|---|---|
| 1ª bateria, com reranker | 0,74 | 0,25 | 0,32 | 0,31 | reranker desligado |
| 1ª bateria, sem reranker | 0,75 | 0,33 | 0,44 | 0,46 | referência |
| + A+B (vizinhos + descrições) | 0,78 | 0,72 | 0,44 | 0,46 | adotado |
| + busca (b) RRF w 0,8 / k 30 | **0,78** | **0,83** | **0,46** | **0,49** | **padrão atual** |
| + reescrita da consulta | 0,78 | 0,80 | 0,46 | 0,49 | desligado |
| + votação de labels (n = 3) | 0,77 | 0,67 | 0,46 | 0,49 | desligado |
| testset v2 (216), controle (b) | 0,79 | 0,75 | 0,46 | 0,49 | referência |
| + busca separada 6+4 | 0,78 | 0,70 | 0,48 | 0,50 | só no lógico |

Outros resultados:
- **Guardrails** (30 issues): F1 subiu de 0,72 para 0,78; 95% de recusa em perguntas fora do tema. (O "22 → 0 refs fora das fontes" é artefato da medição, não alucinação.) Na busca2, 14 labels inventados foram barrados.
- **Busca separada no lógico:** nDCG +0,022 (IC95 [0,004; 0,045]) e related_hit +6,1 pp, de 59,8% para 65,9%.
- **Hipóteses, comparando configurações na 1ª bateria:**
  - Semântica vs léxica: nDCG da densa 0,39, BM25 0,43, híbrida 0,44. Porém a densa teve o melhor F1 de integration: (0,56).
  - Multifonte (base+extras) vs base: nDCG 0,43 vs 0,44, ou seja, extras não ajudaram.
  - Chat com RAG: suporte das citações 4,95 contra 3,0 sem RAG; latência mediana de 21 s contra 56 s.
- **Latência da triagem** (864 respostas): mediana 22,5 s, p90 29,9 s.
- **Custo total no Modal:** ~US$ 15,6.

**7. Limitações**
- O gabarito de busca tem só 82 issues. O método automático encontrou gabarito para 0 das 134 issues novas, e a maioria dos IC95 cruza zero.
- Há ruído entre rodadas: a mesma configuração variou ~5 pp no related_hit.
- O recall da busca é baixo (Recall@10 ~0,58), e é ele o gargalo, não o LLM.
- O juiz LLM saturou (notas ~4,9 de 5) e é da mesma família do modelo avaliado.
- Os labels são comparados com os atuais, que são ambíguos (exemplo #34022).

**8. Conclusões e melhorias futuras**
- O ganho maior veio do prompt (A+B: integration: de 0,33 para 0,83), não do reranker, que piorou a busca.
- Próximos passos:
  - anotação manual de 30 issues com pooling (`anotacao_gabarito.xlsx`);
  - deduplicar a lista de relacionados;
  - reescrever a frase quando o guardrail remove uma citação;
  - decidir sobre o corte de relacionados (precisão de 0,22 para 0,32, mas related_hit −14,6 pp);
  - recalibrar o MIN_SCORE.
