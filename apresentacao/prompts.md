# Prompts de triagem (como estão no backend)

Fonte: `backend/rag/prompts.py` (`DEFAULT_PROMPTS`, `triage_messages`) e `backend/rag/triage_aids.py`. Para triagem, a pasta `prompts/` não sobrescreve nada; ela só tem `chat_strict.txt`, que serve ao /chat.

## System prompt (modo guardrails = `triage_strict` + `triage_schema`)
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
Sem guardrails, o system prompt é só este: "Você ajuda a fazer a triagem de issues do repositório backstage/backstage. Escreva em português." (seguido do mesmo schema).

## User prompt (template, na ordem de montagem)
```
LABELS PERMITIDAS:
- type:bug: Algo não funciona como deveria (erro, crash, regressão, comportamento errado).
- area:catalog: Software Catalog: entidades, catalog-info.yaml, processors, entity providers, ingestão, relações.
- integration:gitlab: Envolve GitLab (gitlab.com ou self-hosted: OAuth, provider, publish:gitlab).
- …  (76 labels; descrições próprias quando a do GitHub é vazia/vaga — melhoria "B")

EXEMPLOS RESOLVIDOS (issues antigas, com os labels que os mantenedores aplicaram):
Exemplo 1 - "[plugin-scaffolder-backend-module-github] customProperties should support a list of strings"
Labels: type:bug, area:scaffolder, integration:github
Por quê: erro (bug) numa action do Scaffolder (publish:github) que fala com o GitHub.
Exemplo 2 - "GitLab OAuth fails with 'Missing session cookie' despite correct CORS" → type:bug, area:auth, integration:gitlab
Exemplo 3 - "TechDocs Preview is broken in 1.8.8, 1.8.9" → type:bug, area:techdocs (sem integration:*)
Regras práticas: use exatamente um type:*; use area:* da parte do Backstage afetada (normalmente 1);
use integration:* SÓ quando a issue envolve um provedor externo específico (GitHub, GitLab, Azure, AWS...).

CONTEXTO:
[1] (issue #28190) 🐛 Bug Report: GitlabUrlReader not working since undici change - https://github.com/...   (ilustrativo)
<texto do chunk>
[2] (doc-integrations/gitlab/...) <título> - <url>
<texto do chunk>
…  (top-k da busca híbrida; no lógico: 6 issues/PRs + 4 docs)

LABELS DAS ISSUES/PRS PARECIDAS (labels reais aplicados pelos mantenedores; use como referência,
não copie sem conferir se valem para a issue nova):
- [1] issue #28190: type:bug, integration:gitlab   (linha ilustrativa)
- …  (até 5 vizinhos, só itens anteriores ao corte T = 22/04/2026 — melhoria "A")

ISSUE NOVA:
Título: <título>

<corpo>
```

## Correção automática (se o JSON não passar no schema)
```
Sua resposta anterior não passou na validação do schema: <erro (até 800 caracteres)>
Responda novamente APENAS com o objeto JSON no formato pedido.
```

## Pós-processamento (guardrails, no código e não no prompt)
- Labels fora da lista permitida são removidos.
- `related`, `docs` e citações `[n]` que não estão no CONTEXTO são removidos; nos dados, aparecem no campo `removed`.
- Quando o assunto não é Backstage, o sistema recusa a resposta (recusa fora de tema 95%).
