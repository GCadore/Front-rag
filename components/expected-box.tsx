"use client";

import type { DemoExample } from "@/lib/demo-examples";
import type { TriageResult } from "@/lib/types";

// Gabarito do exemplo carregado, marcando o que a triagem acertou
export default function ExpectedBox({ example, result }: { example: DemoExample; result: TriageResult }) {
  const suggested = new Set(result.labels.map((l) => l.name));
  const relatedIds = new Set([...result.related, ...result.docs].map((r) => r.doc_id));
  const sourceIds = new Set(result.sources.map((s) => s.doc_id));
  const { labels, otherLabels, related } = example.expected;
  const labelHits = labels.filter((l) => suggested.has(l)).length;
  const relatedHits = related.filter((r) => relatedIds.has(r.id)).length;

  return (
    <section className="card expected">
      <div className="card-head">
        <h2>Esperado (gabarito)</h2>
        <a href={example.url} target="_blank" rel="noreferrer" className="muted">
          ver {example.id} no GitHub
        </a>
      </div>
      <p className="muted expected-note">
        {example.kind === "acerto" ? "Exemplo de acerto: " : "Exemplo de erro: "}
        {example.note}.
      </p>

      <h3>
        Labels reais · {labelHits} de {labels.length} sugeridas
      </h3>
      <p className="muted hint">
        Labels que os mantenedores colocaram no GitHub. ✓ a triagem sugeriu · ✗ não sugeriu · tracejadas são labels de
        processo (como stale), fora da avaliação.
      </p>
      <div className="labels">
        {labels.map((l) => (
          <span key={l} className={`pill ${suggested.has(l) ? "hit" : "miss"}`}>
            {suggested.has(l) ? "✓" : "✗"} {l}
          </span>
        ))}
        {otherLabels.map((l) => (
          <span key={l} className="pill other" title="Label de processo, a triagem não sugere">
            {l}
          </span>
        ))}
      </div>

      <h3>
        Relacionados do gabarito
        {related.length > 0 && ` · ${relatedHits} de ${related.length} na resposta`}
      </h3>
      {related.length > 0 && (
        <p className="muted hint">
          Issues, PRs e docs ligados de verdade a esta issue (links que o autor escreveu). ✓ está na resposta · ~ a busca
          trouxe, mas o modelo não citou · ✗ a busca não encontrou.
        </p>
      )}
      {related.length === 0 ? (
        <p className="muted">Esta issue não tem itens relacionados no gabarito.</p>
      ) : (
        <ul className="expected-related">
          {related.map((r) => {
            const status = relatedIds.has(r.id) ? "hit" : sourceIds.has(r.id) ? "partial" : "miss";
            return (
              <li key={r.id} className={status}>
                <span className="mark">{status === "hit" ? "✓" : status === "partial" ? "~" : "✗"}</span>
                <span className="type-tag">{r.type}</span>
                {r.number !== null && <span className="muted">#{r.number}</span>}
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
                <span className="muted status-text">
                  {status === "hit" ? "na resposta" : status === "partial" ? "só nos trechos buscados" : "não encontrado"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
