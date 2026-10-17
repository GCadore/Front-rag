// Modo MOCK_API=true: imita a API em Python, nos mesmos formatos, pra testar a interface sem backend.
// Perguntas com "receita" ou "futebol" simulam fora do assunto. Os scores e os trechos mudam com a
// configuração, pra comparação lado a lado ter diferença visível.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { stripMentions, unknownMentions } from "./citations";
import {
  CHAT_TOP_K,
  REFUSAL,
  TRIAGE_TOP_K,
  normalizeConfig,
  type ChatMessage,
  type ChatResult,
  type CompareRequest,
  type RagConfig,
  type Source,
  type Timings,
  type TriageLabel,
  type TriageRelated,
  type TriageResult,
} from "./types";

const MIN_SCORE = 0.35;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Chunk = Omit<Source, "n" | "score"> & { number?: number; state?: string };

const ISSUE: Chunk = {
  id: "issue-24512-000",
  doc_id: "issue-24512",
  type: "issue",
  number: 24512,
  state: "closed",
  title: "Catalog entities stop refreshing when the GitHub integration token expires",
  url: "https://github.com/backstage/backstage/issues/24512",
  snippet: "Catalog entities fail to refresh when the GitHub integration token expires. Workaround: rotate the token and restart the backend.",
};
const DOC_ENTITY: Chunk = {
  id: "doc-life-of-an-entity-002",
  doc_id: "doc-life-of-an-entity",
  type: "doc",
  title: "The Life of an Entity",
  url: "https://backstage.io/docs/features/software-catalog/life-of-an-entity",
  snippet: "The catalog processes entities in a loop; errors are visible in the entity's Inspect dialog.",
};
const DOC_APPS: Chunk = {
  id: "doc-github-apps-001",
  doc_id: "doc-github-apps",
  type: "doc",
  title: "GitHub Apps",
  url: "https://backstage.io/docs/integrations/github/github-apps",
  snippet: "GitHub App credentials are refreshed automatically; personal access tokens are not.",
};
const PR: Chunk = {
  id: "pr-24630-000",
  doc_id: "pr-24630",
  type: "pr",
  number: 24630,
  state: "merged",
  title: "fix(catalog): refresh GitHub token before processing",
  url: "https://github.com/backstage/backstage/pull/24630",
  snippet: "Refreshes the integration token before each processing loop so expired tokens no longer stall the catalog.",
};
const ADR: Chunk = {
  id: "adr-013-000",
  doc_id: "adr-013",
  type: "adr",
  title: "ADR013: Proper use of HTTP fetching libraries",
  url: "https://backstage.io/docs/architecture-decisions/adrs-adr013",
  snippet: "Backend plugins should use the shared fetch utilities so credentials and retries are handled consistently.",
};
const CHANGELOG: Chunk = {
  id: "changelog-catalog-backend-1-20-000",
  doc_id: "changelog-catalog-backend-1-20",
  type: "changelog",
  title: "@backstage/plugin-catalog-backend 1.20.0",
  url: "https://github.com/backstage/backstage/blob/master/plugins/catalog-backend/CHANGELOG.md",
  snippet: "Fixed a refresh loop stall after migrating to the new backend system; catalog.processingInterval is now respected.",
};

const POOLS: Record<RagConfig["index"], Chunk[]> = {
  enxuto: [ISSUE, DOC_ENTITY],
  base: [ISSUE, DOC_ENTITY, DOC_APPS, PR],
  base_extras: [ISSUE, DOC_ENTITY, DOC_APPS, PR, CHANGELOG],
  logico: [ISSUE, DOC_ENTITY, ADR],
};

const isOffTopic = (q: string) => /receita|futebol/i.test(q);

async function retrieve(query: string, config: RagConfig, topK: number) {
  const base = isOffTopic(query) ? 0.12 : 0.78;
  const bonus = { dense: 0.02, bm25: -0.09, hybrid: 0.06 }[config.search] + (config.reranker ? 0.05 : 0);
  const pool = POOLS[config.index];
  // Sem reranker, BM25 põe o doc genérico na frente da issue
  const ordered = config.search === "bm25" && !config.reranker ? [pool[1], pool[0], ...pool.slice(2)] : pool;
  const retrieval = { dense: 160, bm25: 90, hybrid: 230 }[config.search];
  const rerank = config.reranker ? 180 : 0;
  await sleep(retrieval + rerank);
  const hits = ordered.slice(0, topK).map((c, i) => ({ ...c, n: i + 1, score: Math.max(0, +(base + bonus - i * 0.07).toFixed(3)) }));
  return { hits, timings: { retrieval, rerank } };
}

const toSource = (h: Chunk & { n: number; score: number }): Source => ({
  n: h.n,
  id: h.id,
  doc_id: h.doc_id,
  type: h.type,
  title: h.title,
  url: h.url,
  snippet: h.snippet,
  score: h.score,
});

function chatAnswer(question: string, sources: Source[], config: RagConfig) {
  if (!config.rag)
    // Sem contexto o modelo "chuta" com confiança, que é o ponto da comparação
    return `Modo de teste, sem RAG. Sobre **${question}**: isso costuma acontecer por cache do catálogo. Rode \`yarn backstage-cli catalog:refresh\` e atualize para a versão 1.18, onde a issue #23001 corrigiu o problema. Mais detalhes em https://backstage.io/docs/catalog-cache.`;
  if (isOffTopic(question))
    return `Modo de teste, sem guardrails. Os trechos encontrados não falam disso, mas posso tentar: **${question}** não parece ter relação com o Backstage [1].`;
  const n = (doc: Chunk) => sources.find((s) => s.doc_id === doc.doc_id)?.n;
  const cite = (doc: Chunk, text: string) => (n(doc) ? ` ${text} [${n(doc)}].` : "");
  return (
    `Modo de teste. Sobre **${question}**:` +
    cite(ISSUE, "as entidades do catálogo deixam de atualizar quando o token da integração com o GitHub expira") +
    cite(DOC_ENTITY, "Os erros aparecem no diálogo Inspect da entidade") +
    cite(DOC_APPS, "Com GitHub App as credenciais renovam sozinhas") +
    cite(PR, "Um PR passou a renovar o token antes de cada ciclo de processamento") +
    cite(ADR, "Plugins de backend devem usar os utilitários de fetch compartilhados") +
    cite(CHANGELOG, "Depois da migração pro novo backend, a versão 1.20 corrigiu o travamento do refresh") +
    // Cita um trecho que não existe de propósito, pra mostrar o guardrail de saída
    ` Isso já foi corrigido na versão 2.0 [${sources.length + 1}].`
  );
}

function invalidCitations(text: string, k: number) {
  return [...new Set([...text.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])))].filter((n) => n < 1 || n > k);
}

const stripInvalid = (text: string, invalid: number[]) =>
  invalid.reduce((t, n) => t.replaceAll(` [${n}]`, "").replaceAll(`[${n}]`, ""), text);

const lastQuestion = (messages: ChatMessage[] | undefined) =>
  [...(messages ?? [])].reverse().find((m) => m.role === "user")?.content ?? "";

interface ChatPlan {
  config: RagConfig;
  sources: Source[];
  text: string; // texto que o "modelo" gerou
  refused: boolean;
  removed: number[];
  mentions: string[];
  timings: Omit<Timings, "total" | "llm">;
}

async function planChat(question: string, rawConfig: unknown): Promise<ChatPlan> {
  const config = normalizeConfig(rawConfig);
  if (!config.rag) return { config, sources: [], text: chatAnswer(question, [], config), refused: false, removed: [], mentions: [], timings: {} };

  const { hits, timings } = await retrieve(question, config, config.top_k ?? CHAT_TOP_K);
  const sources = hits.map(toSource);
  const top = Math.max(0, ...sources.map((s) => s.score));
  // Guardrail de entrada: score baixo demais, nem chama o modelo
  if (config.guardrails && top < MIN_SCORE) return { config, sources, text: REFUSAL, refused: true, removed: [], mentions: [], timings };

  const text = chatAnswer(question, sources, config);
  const removed = config.guardrails ? invalidCitations(text, sources.length) : [];
  const haystack = hits.map((h) => `${h.title} ${h.snippet} ${h.url ?? ""} #${h.number ?? ""} ${question}`).join(" ");
  const mentions = config.guardrails ? unknownMentions(text, haystack) : [];
  return { config, sources, text, refused: false, removed, mentions, timings };
}

const LLM_START_MS = 450;
const TOKEN_MS = 15;

export async function mockChat(body: { messages?: ChatMessage[]; config?: unknown }): Promise<ChatResult> {
  const t0 = Date.now();
  const plan = await planChat(lastQuestion(body.messages), body.config);
  const tl = Date.now();
  if (!plan.refused) await sleep(LLM_START_MS + 300);
  return {
    answer: stripMentions(stripInvalid(plan.text, plan.removed), plan.mentions),
    sources: plan.sources,
    rag: plan.config.rag,
    config: plan.config,
    timings_ms: { ...plan.timings, llm: plan.refused ? 0 : Date.now() - tl, total: Date.now() - t0 },
    refused: plan.refused,
    removed_citations: plan.removed,
    removed_mentions: plan.mentions,
  };
}

// SSE no formato da spec: sources, token..., done (ou error)
export function mockChatStream(body: { messages?: ChatMessage[]; config?: unknown }): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (event: string, data: unknown) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      try {
        const t0 = Date.now();
        const plan = await planChat(lastQuestion(body.messages), body.config);
        send("sources", { sources: plan.sources });
        const tl = Date.now();
        if (!plan.refused) await sleep(LLM_START_MS);
        // A recusa vem de uma vez; a resposta do "modelo", palavra por palavra
        for (const word of plan.refused ? [plan.text] : plan.text.split(/(\s+)/)) {
          if (!word) continue;
          if (!plan.refused) await sleep(TOKEN_MS);
          send("token", { t: word });
        }
        send("done", {
          timings_ms: { ...plan.timings, llm: plan.refused ? 0 : Date.now() - tl, total: Date.now() - t0 },
          refused: plan.refused,
          removed_citations: plan.removed,
          removed_mentions: plan.mentions,
        });
      } catch (err) {
        send("error", { message: err instanceof Error ? err.message : String(err) });
      } finally {
        controller.close();
      }
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache" } });
}

// Mesmo filtro da spec pra GET /labels
let labelsCache: { name: string; description?: string; color?: string }[] | null = null;
export async function mockLabels() {
  if (!labelsCache) {
    try {
      labelsCache = JSON.parse(await readFile(path.join(process.cwd(), "data", "labels.json"), "utf8"));
    } catch {
      labelsCache = [{ name: "area:catalog" }, { name: "integration:github" }, { name: "type:bug" }, { name: "needs:more-info" }];
    }
  }
  return labelsCache!.filter(
    (l) => /^(type|area|integration|domain):/.test(l.name) || l.name === "needs:repro" || l.name === "needs:more-info",
  );
}

export async function mockTriage(body: { title?: string; body?: string; config?: unknown }): Promise<TriageResult> {
  const t0 = Date.now();
  const config = normalizeConfig(body.config);
  const title = body.title ?? "";
  const text = body.body ?? "";
  const query = `${title}\n${text}`;
  const empty = { labels: [], component: null, related: [], docs: [], removed: { labels: [], related: [] } };

  let hits: (Chunk & { n: number; score: number })[] = [];
  let timings: Omit<Timings, "total"> = {};
  if (config.rag) ({ hits, timings } = await retrieve(query, config, config.top_k ?? TRIAGE_TOP_K));
  const sources = hits.map(toSource);
  const top = Math.max(0, ...sources.map((s) => s.score));

  if (config.rag && config.guardrails && top < MIN_SCORE)
    return {
      ...empty,
      needs_more_info: false,
      explanation: REFUSAL,
      sources,
      timings_ms: { ...timings, llm: 0, total: Date.now() - t0 },
      refused: true,
      config,
    };

  await sleep(700);
  const k = sources.length;
  const issue = hits.find((h) => h.doc_id === ISSUE.doc_id);
  const pr = hits.find((h) => h.doc_id === PR.doc_id);
  const docHits = hits.filter((h) => h.type === "doc" || h.type === "adr").slice(0, 2);

  // O que o "modelo" devolveu. Inclui erros de propósito: uma label que não existe e um relacionado inventado.
  const rawLabels: TriageLabel[] = [
    { name: "area:catalog", confidence: "alta" },
    { name: "integration:github", confidence: "media" },
    { name: "type:bug", confidence: "media" },
    { name: "bug-critico", confidence: "baixa" },
  ];
  const invented: TriageRelated = {
    n: k + 2,
    doc_id: config.rag ? "issue-99999" : "issue-23001",
    type: "issue",
    number: config.rag ? 99999 : 23001,
    title: config.rag ? "Catalog refresh broken (duplicada)" : "Cache do catálogo corrompido na versão 1.17",
    url: `https://github.com/backstage/backstage/issues/${config.rag ? 99999 : 23001}`,
    state: "closed",
    reason: "Problema parecido",
  };
  const realRelated: TriageRelated[] = [issue, pr].flatMap((h) =>
    h
      ? [
          {
            n: h.n,
            doc_id: h.doc_id,
            type: h.type,
            number: h.number,
            title: h.title,
            url: h.url,
            state: h.state,
            reason: h === issue ? "Mesmo sintoma com token expirado" : "Corrige a renovação do token",
            score: h.score,
          },
        ]
      : [],
  );
  const cite = (h: { n: number } | undefined) => (h ? ` [${h.n}]` : "");
  const explanation = config.rag
    ? `Parece o mesmo caso da issue #24512, em que o token expirado impede o refresh${cite(issue)}. ` +
      (docHits[0] ? `Os erros devem aparecer no Inspect da entidade [${docHits[0].n}]. ` : "") +
      `Veja também #99999 [${k + 2}].`
    : "Problema de cache no catálogo, comum em versões antigas. Atualize para a versão 1.18, a issue #23001 corrigiu isso. Veja https://backstage.io/docs/catalog-cache.";

  // Como na API: labels e relacionados são sempre validados (a tela mostra como dado real).
  // Os guardrails ligam a limpeza de citações [n] e de menções fora dos trechos.
  const allowed = new Set((await mockLabels()).map((l) => l.name));
  const removed = { labels: [] as string[], related: [] as string[], citations: [] as number[], mentions: [] as string[] };
  const labels = rawLabels.filter((l) => allowed.has(l.name) || (removed.labels.push(l.name), false));
  const related = [...realRelated, invented].filter(
    (r) => hits.some((h) => h.n === r.n && h.doc_id === r.doc_id) || (removed.related.push(r.doc_id), false),
  );
  let finalExplanation = explanation;
  if (config.rag && config.guardrails) {
    removed.citations = invalidCitations(explanation, k);
    const haystack = hits.map((h) => `${h.title} ${h.snippet} ${h.url ?? ""} #${h.number ?? ""}`).join(" ");
    removed.mentions = unknownMentions(explanation, haystack);
    finalExplanation = stripMentions(stripInvalid(explanation, removed.citations), removed.mentions);
  }

  return {
    labels,
    component: "catalog",
    related,
    docs: docHits.map((h) => ({ n: h.n, doc_id: h.doc_id, type: h.type, title: h.title, url: h.url })),
    needs_more_info: text.trim().length < 40,
    explanation: finalExplanation,
    sources,
    removed,
    timings_ms: { ...timings, llm: 700, total: Date.now() - t0 },
    refused: false,
    config,
  };
}

export async function mockCompare(body: CompareRequest) {
  const configs = (body.configs ?? []).slice(0, 4);
  const messages = body.messages?.length ? body.messages : [{ role: "user" as const, content: `${body.title ?? ""}\n${body.body ?? ""}`.trim() }];
  const results = await Promise.all(
    configs.map((config) => (body.mode === "chat" ? mockChat({ messages, config }) : mockTriage({ title: body.title, body: body.body, config }))),
  );
  return { results };
}

export function mockHealth() {
  return { status: "ok", indices: Object.keys(POOLS), llm: "mock", reranker: true, mock: true };
}
