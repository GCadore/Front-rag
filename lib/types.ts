// Tipos que espelham a API em Python (backend/API_SPEC.md, seção 4)

export type Role = "user" | "assistant";

export interface ChatMessage {
  role: Role;
  content: string;
}

export type IndexName = "base" | "enxuto" | "base_extras" | "logico";
export type SearchMode = "dense" | "bm25" | "hybrid";

// Configuração escolhida no painel lateral; vai junto em cada requisição
export interface RagConfig {
  rag: boolean; // false = pergunta direto pro Qwen, sem busca
  index: IndexName;
  search: SearchMode;
  reranker: boolean;
  guardrails: boolean;
  top_k?: number; // sem valor, a API usa o padrão dela (10 na triagem)
}

export const CHAT_TOP_K = 8;
export const TRIAGE_TOP_K = 10;

export const DEFAULT_CONFIG: RagConfig = {
  rag: true,
  index: "base",
  search: "hybrid",
  reranker: true,
  guardrails: true,
};

export const INDEX_LABELS: Record<IndexName, string> = {
  base: "Base",
  enxuto: "Enxuto",
  base_extras: "Base com extras",
  logico: "Lógico",
};

export const SEARCH_LABELS: Record<SearchMode, string> = {
  dense: "Dense",
  bm25: "BM25",
  hybrid: "Híbrida",
};

// Aceita só valores conhecidos; o resto cai no padrão. Também migra o antigo "rerank" pra "reranker".
export function normalizeConfig(raw: unknown): RagConfig {
  const c = (raw ?? {}) as Record<string, unknown>;
  const bool = (v: unknown, fallback: boolean) => (typeof v === "boolean" ? v : fallback);
  const index = Object.keys(INDEX_LABELS).includes(c.index as string) ? (c.index as IndexName) : DEFAULT_CONFIG.index;
  const search = Object.keys(SEARCH_LABELS).includes(c.search as string) ? (c.search as SearchMode) : DEFAULT_CONFIG.search;
  const config: RagConfig = {
    rag: bool(c.rag, DEFAULT_CONFIG.rag),
    index,
    search,
    reranker: bool(c.reranker ?? c.rerank, DEFAULT_CONFIG.reranker),
    guardrails: bool(c.guardrails, DEFAULT_CONFIG.guardrails),
  };
  if (typeof c.top_k === "number" && Number.isInteger(c.top_k) && c.top_k > 0) config.top_k = c.top_k;
  return config;
}

export type SourceType = "issue" | "pr" | "comment" | "doc" | "adr" | "changelog" | "commit" | "review";

// Trecho recuperado, numerado [n] como aparece no prompt
export interface Source {
  n: number;
  id: string;
  doc_id: string;
  source?: string; // "issue #119", "pr #600" ou o doc_id
  number?: number | null;
  type: SourceType | string;
  title: string;
  url?: string;
  snippet: string;
  score: number;
}

export interface Timings {
  retrieval?: number;
  rerank?: number;
  llm?: number;
  total: number;
}

// POST /chat sem streaming (e cada item de /compare no modo chat)
export interface ChatResult {
  answer: string;
  sources: Source[];
  rag: boolean;
  config: RagConfig;
  timings_ms: Timings;
  refused: boolean;
  removed_citations?: number[];
  removed_mentions?: string[]; // issues, PRs e links que não estão nos trechos
}

// Último evento do SSE de /chat
export interface ChatDone {
  timings_ms: Timings;
  refused: boolean;
  removed_citations?: number[];
  removed_mentions?: string[];
  answer?: string; // não está na spec, mas se a API mandar o texto da recusa aqui, usamos
}

// Eventos do SSE de /chat, já decodificados
export type StreamEvent =
  | { type: "sources"; sources: Source[] }
  | { type: "token"; t: string }
  | ({ type: "done" } & ChatDone)
  | { type: "error"; message: string };

export type Confidence = "alta" | "media" | "baixa";

export interface TriageLabel {
  name: string;
  confidence: Confidence;
}

export interface TriageRelated {
  n: number;
  doc_id: string;
  type: SourceType | string;
  number?: number | null;
  title: string;
  url?: string;
  state?: string | null;
  reason: string;
  score?: number;
}

export interface TriageDoc {
  n: number;
  doc_id: string;
  type: SourceType | string;
  title: string;
  url?: string;
}

// POST /triage (e cada item de /compare no modo triagem)
export interface TriageResult {
  labels: TriageLabel[];
  component: string | null;
  related: TriageRelated[];
  docs: TriageDoc[];
  needs_more_info: boolean;
  explanation: string;
  sources: Source[];
  // A API pode mandar só as chaves que tiveram remoção
  removed?: { labels?: string[]; related?: string[]; docs?: unknown[]; citations?: number[]; mentions?: string[] };
  timings_ms: Timings;
  refused: boolean;
  config?: RagConfig;
  error?: string;
}

export type CompareMode = "chat" | "triage";

export interface CompareRequest {
  title: string;
  body: string;
  configs: RagConfig[];
  mode: CompareMode;
  messages?: ChatMessage[];
}

// Uma configuração que falhou em /compare volta assim, sem derrubar as outras
export interface CompareFailure {
  error: string; // "llm_unavailable" quando o LLM está frio
  retry?: boolean;
  message?: string;
  status: number;
  config?: RagConfig;
}

export interface CompareResponse {
  results: (ChatResult | TriageResult | CompareFailure)[];
}

export const isCompareFailure = (r: unknown): r is CompareFailure =>
  typeof r === "object" && r !== null && typeof (r as CompareFailure).status === "number" && "error" in r;

export const REFUSAL = "Não encontrei nada sobre isso na base do Backstage.";
