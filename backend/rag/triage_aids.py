"""Ajudas de precisão para a triagem (podem ser ligadas/desligadas por env ou por requisição).

A) Labels dos vizinhos (TRIAGE_NEIGHBOR_LABELS): os labels reais (type:/area:/integration:) das
   issues/PRs mais parecidas que a busca trouxe entram no prompt como referência ("few-shot").
   Proteção contra vazamento: ignora a própria issue (mesmo título) e tudo criado depois do corte
   (TRIAGE_NEIGHBOR_CUTOFF, padrão 2026-04-22, o mesmo corte do testset).
B) Descrições dos labels + exemplos resolvidos (TRIAGE_LABEL_DESCRIPTIONS): uma linha por label de
   triagem (as do labels.json têm prioridade quando existem) e 3 triagens de exemplo de issues
   anteriores ao corte que NÃO estão no testset.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .retrieval import Hit

NEIGHBOR_PREFIXES = ("type:", "area:", "integration:")
NEIGHBOR_TYPES = {"issue", "pr"}
DEFAULT_CUTOFF = "2026-04-22T00:00:00Z"

# Uma linha por label; usadas quando o labels.json não tem descrição (ou tem uma muito vaga).
LABEL_DESCRIPTIONS: dict[str, str] = {
    "type:bug": "Algo não funciona como deveria (erro, crash, regressão, comportamento errado).",
    "type:suggestion": "Pedido de funcionalidade nova ou melhoria de algo que já funciona.",
    "type:docs": "Problema ou pedido na documentação (docs faltando, erradas ou confusas).",
    "type:maintenance": "Manutenção: atualização de dependências, limpeza, refatoração, CI.",
    "area:auditor": "Plugin/serviço de auditoria (auditor) e eventos de auditoria.",
    "area:auth": "Autenticação e login: providers (GitHub, GitLab, Google, OIDC...), sessões, tokens de usuário, sign-in resolvers.",
    "area:catalog": "Software Catalog: entidades, catalog-info.yaml, processors, entity providers, ingestão, relações.",
    "area:core": "Núcleo do framework Backstage (core-*), APIs centrais do app.",
    "area:design-system": "Componentes de UI / design system (Backstage UI, core-components, temas).",
    "area:discoverability": "Encontrar coisas no portal: navegação, catálogo/explore, experiência de descoberta.",
    "area:documentation": "Melhorias ou adições à documentação do projeto.",
    "area:events": "Events backend / event bus e módulos de eventos (webhooks).",
    "area:framework": "Frameworks de plugin: new frontend system, backend system, extensões, service-to-service auth, DI.",
    "area:home": "Plugin Home (página inicial personalizável).",
    "area:kubernetes": "Plugin Kubernetes (ver workloads no Backstage) - não é sobre fazer deploy do Backstage em k8s.",
    "area:microsite": "Site backstage.io (microsite).",
    "area:notifications": "Plugin de notificações e signals.",
    "area:openapi-tooling": "Ferramentas de OpenAPI (repo-tools schema, clientes gerados, validação).",
    "area:operations": "Operar o Backstage: deploy, Docker, configuração em produção, banco de dados, performance, observabilidade.",
    "area:permission": "Permission framework: políticas, regras, conditional decisions, RBAC.",
    "area:scaffolder": "Scaffolder / Software Templates: templates, actions (publish:*, fetch:*), dry-run, task runs.",
    "area:search": "Search: indexação, collators, engines (Lunr, Postgres, Elasticsearch/OpenSearch), UI de busca.",
    "area:storybook": "Storybook dos componentes.",
    "area:techdocs": "TechDocs: geração/publicação de docs (mkdocs, techdocs-cli), leitor e add-ons.",
    "area:tooling": "Ferramentas de desenvolvimento: backstage-cli, create-app, build, lint, testes, yarn, versões do Node.",
    "integration:aws": "Envolve AWS (S3, CodeCommit, ECR, Cognito, ALB...).",
    "integration:azure": "Envolve Azure / Azure DevOps (repos, pipelines, Entra ID/MS Graph).",
    "integration:bitbucket-cloud": "Envolve Bitbucket Cloud (bitbucket.org).",
    "integration:bitbucket-server": "Envolve Bitbucket Server / Data Center (self-hosted).",
    "integration:gcp": "Envolve Google Cloud (GCS, GKE, IAP, Google auth).",
    "integration:gerrit": "Envolve Gerrit.",
    "integration:gitea": "Envolve Gitea.",
    "integration:github": "Envolve GitHub (GitHub App, tokens, publish:github, github org/provider, GitHub Enterprise).",
    "integration:gitlab": "Envolve GitLab (gitlab.com ou self-hosted: OAuth, provider, publish:gitlab).",
    "integration:other": "Envolve outra integração externa que não tem label própria.",
}
_VAGUE = re.compile(r"^related to the .* project area$", re.I)

TRIAGE_EXAMPLES = """EXEMPLOS RESOLVIDOS (issues antigas, com os labels que os mantenedores aplicaram):

Exemplo 1 - "[plugin-scaffolder-backend-module-github] customProperties should support a list of strings"
Resumo: ao passar uma lista em customProperties no publish:github, a action falha com "is not of a type(s) string" depois de atualizar o módulo GitHub do scaffolder.
Labels: type:bug, area:scaffolder, integration:github
Por quê: erro (bug) numa action do Scaffolder (publish:github) que fala com o GitHub.

Exemplo 2 - "GitLab OAuth fails with 'Missing session cookie' despite correct CORS"
Resumo: login com o provider GitLab falha com AuthenticationError "Missing session cookie" após seguir a doc de auth.
Labels: type:bug, area:auth, integration:gitlab
Por quê: falha de login (auth) com o provider do GitLab. Faltam detalhes de config, então needs_more_info pode ser true.

Exemplo 3 - "TechDocs Preview is broken in 1.8.8, 1.8.9"
Resumo: `npx @techdocs/cli serve` devolve 404 nas versões novas; versões antigas funcionam (regressão).
Labels: type:bug, area:techdocs
Por quê: regressão do techdocs-cli. Não envolve integração externa, então nenhum integration:*.

Regras práticas: use exatamente um type:*; use area:* da parte do Backstage afetada (normalmente 1); use integration:* SÓ quando a issue envolve um provedor externo específico (GitHub, GitLab, Azure, AWS...)."""


def label_description(label: dict[str, Any]) -> str:
    """Descrição de uma linha: a do labels.json, a não ser que esteja vazia/vaga."""
    own = str(label.get("description") or "").strip()
    ours = LABEL_DESCRIPTIONS.get(str(label.get("name", "")))
    if ours and (not own or _VAGUE.match(own) or len(own) < 25):
        return ours
    return own or (ours or "")


def parse_cutoff(value: str | None) -> float | None:
    """ISO 8601 -> epoch (s). Vazio/"none" desliga o filtro de data."""
    if value is None:
        value = DEFAULT_CUTOFF
    value = value.strip()
    if not value or value.lower() in {"none", "off", "false", "0"}:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _norm_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _created_ts(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000.0 if value > 1e11 else 1.0)
    try:
        return parse_cutoff(str(value))
    except ValueError:
        return None


def _labels_of(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("labels") or ""
    items = raw if isinstance(raw, list) else re.split(r"[|,]", str(raw))
    return [s.strip() for s in items if s and s.strip().startswith(NEIGHBOR_PREFIXES)]


def neighbor_labels(
    hits: list["Hit"],
    title: str,
    cutoff_ts: float | None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Labels reais das k issues/PRs mais parecidas (na ordem da busca), sem vazamento.

    Exclui: a própria issue (título igual), itens criados depois do corte e itens sem labels de triagem.
    Retorna [{"n": nº do trecho no CONTEXTO, "ref": "issue #123", "doc_id", "labels": [...]}].
    """
    me = _norm_title(title)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, hit in enumerate(hits, start=1):
        meta = hit.metadata or {}
        kind = str(meta.get("type", ""))
        if kind not in NEIGHBOR_TYPES or hit.doc_id in seen:
            continue
        seen.add(hit.doc_id)
        if me and _norm_title(str(meta.get("title", ""))) == me:
            continue  # a própria issue
        created = _created_ts(meta.get("created_at"))
        if cutoff_ts is not None and created is not None and created >= cutoff_ts:
            continue  # posterior ao corte
        labels = _labels_of(meta)
        if not labels:
            continue
        out.append({"n": n, "ref": hit.source_label, "doc_id": hit.doc_id, "labels": labels})
        if len(out) >= k:
            break
    return out


def format_neighbors(neighbors: list[dict[str, Any]]) -> str:
    lines = [f"- [{nb['n']}] {nb['ref']}: {', '.join(nb['labels'])}" for nb in neighbors]
    return (
        "LABELS DAS ISSUES/PRS PARECIDAS (labels reais aplicados pelos mantenedores; use como referência, "
        "não copie sem conferir se valem para a issue nova):\n" + "\n".join(lines)
    )
