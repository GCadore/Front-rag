"use client";

import ReactMarkdown from "react-markdown";
import MetricsBar from "@/components/metrics-bar";
import { REFUSAL, type RagConfig, type TriageResult as Triage } from "@/lib/types";

const CONFIANCA = { alta: "alta", media: "média", baixa: "baixa" };

// Resultado de /api/triage: usado na página de triagem e em cada coluna da comparação
export default function TriageResult({ data, config }: { data: Triage; config?: RagConfig }) {
  const cfg = data.config ?? config;

  if (data.refused)
    return (
      <>
        <div className="notice">{data.error ?? data.explanation ?? REFUSAL}</div>
        <MetricsBar timings={data.timings_ms} sources={data.sources} config={cfg} />
      </>
    );

  // A API pode mandar só algumas chaves de `removed`
  const removed = {
    labels: data.removed?.labels ?? [],
    related: data.removed?.related ?? [],
    docs: data.removed?.docs ?? [],
    citations: data.removed?.citations ?? [],
    mentions: data.removed?.mentions ?? [],
  };
  const removedCount = Object.values(removed).reduce((n, list) => n + list.length, 0);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Resultado</h2>
        {data.needs_more_info && <span className="pill needs-info">Precisa de mais informações</span>}
      </div>
      {data.component && (
        <p className="muted">
          Componente: <span className="pill">{data.component}</span>
        </p>
      )}

      <h3>Labels</h3>
      <div className="labels">
        {data.labels.length ? (
          data.labels.map((l) => (
            <span key={l.name} className={`pill conf-${l.confidence}`} title={`Confiança ${CONFIANCA[l.confidence] ?? l.confidence}`}>
              {l.name} · {CONFIANCA[l.confidence] ?? l.confidence}
            </span>
          ))
        ) : (
          <span className="muted">nenhuma</span>
        )}
      </div>

      <h3>Relacionados</h3>
      {data.related.length ? (
        <ul className="related">
          {data.related.map((r) => (
            <li key={`${r.n}-${r.doc_id}`}>
              [{r.n}] <span className="type-tag">{r.type}</span> {r.number ? `#${r.number} ` : ""}
              {r.url ? (
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title || r.doc_id}
                </a>
              ) : (
                r.title || r.doc_id
              )}
              {r.state && <span className="muted"> · {r.state}</span>}
              {r.score !== undefined && <span className="muted"> · score {r.score.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}</span>}
              {r.reason && <div className="muted related-reason">{r.reason}</div>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">nenhum</p>
      )}

      {data.docs.length > 0 && (
        <>
          <h3>Documentação</h3>
          <ul className="related">
            {data.docs.map((d) => (
              <li key={`${d.n}-${d.doc_id}`}>
                [{d.n}] <span className="type-tag">{d.type}</span>{" "}
                {d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer">
                    {d.title || d.doc_id}
                  </a>
                ) : (
                  d.title || d.doc_id
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Explicação</h3>
      <div className="bubble">
        <ReactMarkdown>{data.explanation}</ReactMarkdown>
      </div>

      {removedCount > 0 && (
        <div className="warn removed">
          <b>Removido pelos guardrails</b>
          {removed.labels.length > 0 && <div>Labels que não existem no repo: {removed.labels.join(", ")}</div>}
          {removed.related.length > 0 && <div>Relacionados fora dos trechos recuperados: {removed.related.join(", ")}</div>}
          {removed.docs.length > 0 && <div>Docs fora dos trechos recuperados: {removed.docs.map(String).join(", ")}</div>}
          {removed.citations.length > 0 && <div>Citações inválidas: {removed.citations.map((n) => `[${n}]`).join(", ")}</div>}
          {removed.mentions.length > 0 && <div>Referências fora do contexto: {removed.mentions.join(", ")}</div>}
        </div>
      )}

      <MetricsBar timings={data.timings_ms} sources={data.sources} config={cfg} text={data.explanation} />
    </section>
  );
}
