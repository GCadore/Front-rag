"use client";

import { citedNumbers } from "@/lib/citations";
import { INDEX_LABELS, SEARCH_LABELS, type RagConfig, type Source, type Timings } from "@/lib/types";

export const fmtMs = (ms?: number) =>
  ms === undefined ? "–" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;

const fmtScore = (s?: number) => (s === undefined ? "–" : s.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

export function configSummary(c: RagConfig) {
  if (!c.rag) return "Sem RAG";
  return [INDEX_LABELS[c.index], SEARCH_LABELS[c.search], c.reranker ? "reranker" : "sem reranker", c.guardrails ? "guardrails" : "sem guardrails"].join(" · ");
}

// Tempo, score dos trechos e fontes usadas, embaixo de cada resposta.
// "text" é a resposta (ou explicação) final: dela saem os [n] marcados como "usado".
export default function MetricsBar({
  timings,
  sources,
  config,
  text,
}: {
  timings?: Timings;
  sources?: Source[];
  config?: RagConfig;
  text?: string;
}) {
  const list = sources ?? [];
  if (!timings && list.length === 0) return null;
  const cited = new Set(citedNumbers(text ?? ""));
  const top = list.length ? Math.max(...list.map((s) => s.score ?? 0)) : undefined;

  return (
    <div className="metrics">
      {timings && (
        <div className="metrics-row">
          <span title="Tempo total na API">
            <b>{fmtMs(timings.total)}</b> total
          </span>
          {timings.retrieval !== undefined && <span>busca {fmtMs(timings.retrieval)}</span>}
          {!!timings.rerank && <span>rerank {fmtMs(timings.rerank)}</span>}
          {timings.llm !== undefined && <span>LLM {fmtMs(timings.llm)}</span>}
          {(config?.rag ?? list.length > 0) && (
            <span>
              {list.length} trechos · melhor score {fmtScore(top)}
            </span>
          )}
          {config && <span className="metrics-config">{configSummary(config)}</span>}
        </div>
      )}

      {list.length > 0 && (
        <details className="sources">
          <summary>
            {list.length} trechos · {list.filter((s) => cited.has(s.n)).length} usados na resposta
          </summary>
          {list.map((s) => (
            <div key={s.n} className={`source${cited.has(s.n) ? " used" : ""}`}>
              <div className="source-head">
                <b>
                  [{s.n}]{" "}
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.title || s.doc_id}
                    </a>
                  ) : (
                    s.title || s.doc_id
                  )}
                </b>
                {s.type && <span className="type-tag">{s.type}</span>}
                {cited.has(s.n) && <span className="used-tag">usado</span>}
                <span className="score">
                  <span className="score-track">
                    <span className="score-bar" style={{ width: `${Math.min(1, Math.max(0, s.score ?? 0)) * 100}%` }} />
                  </span>
                  {fmtScore(s.score)}
                </span>
              </div>
              <p>{s.snippet}</p>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
