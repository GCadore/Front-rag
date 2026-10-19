# Investigação das 40 linhas "?" da pré-anotação (anotacao_gabarito_pre_LLM_v2.xlsx)

## Como foi feito
- Para cada issue nova li, pela API do GitHub, o corpo, todos os comentários e a timeline. Abri o PR de correção quando havia um citado (#34025, #33773, #30983, commit 91f5ed82 → PR #32082) e as issues irmãs citadas (#34593, node-fetch#1735).
- Para cada candidato li o texto completo do índice e os comentários pela API. Quando o candidato era PR, abri também a lista de arquivos e o diff.
- O arquivo MAPA não foi usado.
- Seguindo as instruções da planilha, o que aconteceu depois (PR de correção, comentários recentes) serviu só para **julgar** os candidatos da lista, nunca para procurar candidatos novos.
- Nas 40 linhas mudaram só as colunas relevância, anotador (`LLM-investigado`) e notas: 120 células no total. O arquivo original ficou intacto.

## Resultado
- **40 linhas "?": 7 viraram S, 33 viraram N, nenhuma ficou "?".**
- Na planilha toda: S 30 → 37, N 556 → 589, "?" 40 → 0.
- Issues com pelo menos 1 S: **14 → 18 de 30**. As novas são #34107, #34651, #35367 e #35734. Ganharam mais um S: #34462, #34615 e #34731.

## As 7 marcadas como S
| Issue | Candidato | Evidência |
|---|---|---|
| #34107 Card da BUI: gradiente vazando no Firefox | pr-33151 | O "gradiente" é a sombra de rolagem do CardBody (animation-timeline: scroll()) em Card.module.css. O #33151 já corrigiu essa sombra aparecendo indevidamente, e a correção real (#34025) muda o mesmo trecho. |
| #34462 Events: request entity too large | issue-31095 | Mesma causa: o router gerado pelo OpenAPI (stub.ts) registra json() com o limite de 100kb. O stack da issue nova é `backend-openapi-utils/src/stub.ts:36`. No scaffolder isso foi corrigido em #30983. |
| #34651 Node 24.17: Premature close | issue-24590 | Mesma família: node-fetch nas chamadas backend→catalog quebra depois de uma mudança de keep-alive no Node (node-fetch#1735). As saídas também se parecem: fixar a versão do Node ou atualizar o node-fetch. |
| #34615 Restringir opções dos filtros | pr-15058 | Mesmos pickers (Owner/Lifecycle), com opções dependentes de outro filtro, e um mantenedor registra a limitação da arquitetura de filtros. |
| #35734 Entidade some das listas após falha no stitch | issue-26997 | Mesmo ponto fraco: as escritas na tabela `search` do performStitching ficam fora de transação, e a issue antiga já sugeria colocá-las numa transação. |
| #35367 Gerador OpenAPI: tipos por status | issue-33953 | Mesmo ponto do gerador: como várias respostas viram tipos (o stub do servidor já gera uma união). |
| #34731 api-docs usa config.schema depreciado | pr-33952 | Explica exatamente esse aviso de depreciação e a migração certa: o configSchema exige zod@^4, e o subpath zod/v4 do v3 não serve. |

## Destaques
- **Mesmo sintoma, outra causa** foi o motivo mais comum de N. Exemplos:
  - #34462 vs #33923: mesma mensagem "request entity too large", mas causada pelo json() do actions registry, já corrigido antes da 1.51.
  - #34757 vs #20715: os mesmos widgets da home sem dados, mas a causa nova é o routeRef removido do analytics (#34593).
- **PR que criou o código não é PR que causou o bug.** Em #34763, o bug veio do PR #32082 (commit 91f5ed82), e o candidato #30051 só criou a versão correta do código. Mesmo raciocínio para #17470 (gerador OpenAPI).
- **Docs genéricos** (life-of-an-entity, FAQ do catálogo, blueprints, notas de release, proxy corporativo) foram todos N depois de lidos por inteiro: nenhum trata do ponto específico da issue.
- **Problema em #35012:** a causa foi uma SearchPage customizada do próprio usuário, então nenhum item do índice serviria de gabarito.
- **Resolvida fora do Backstage:** #34651 foi corrigida no próprio Node (24.18). O único S é análogo, não a mesma correção.
- Três S são de "mesmo mecanismo" e não duplicatas exatas: #24590, #15058 e #33953. Se o grupo quiser um gabarito mais estrito, esses são os candidatos a voltar para N.

O detalhe linha a linha está em `investigacao_pre_LLM_v2.csv`.
