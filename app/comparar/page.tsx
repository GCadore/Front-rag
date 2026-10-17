"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import ConfigForm from "@/components/config-form";
import MetricsBar, { configSummary } from "@/components/metrics-bar";
import PageHeader from "@/components/page-header";
import TriageResult from "@/components/triage-result";
import { postJSON, friendlyError } from "@/lib/api";
import { stripCitations, stripMentions } from "@/lib/citations";
import {
  CHAT_TOP_K,
  DEFAULT_CONFIG,
  REFUSAL,
  type ChatResult,
  type CompareMode,
  type CompareRequest,
  type CompareResponse,
  type RagConfig,
  type TriageResult as Triage, isCompareFailure } from "@/lib/types";

interface Side {
  config: RagConfig;
  chat?: ChatResult;
  triage?: Triage;
  error?: string;
}

// Comparações prontas pra apresentação
const PRESETS: { label: string; a: Partial<RagConfig>; b: Partial<RagConfig> }[] = [
  { label: "Com RAG vs sem RAG", a: {}, b: { rag: false } },
  { label: "Base vs enxuto", a: { index: "base" }, b: { index: "enxuto" } },
  { label: "Híbrida vs BM25", a: { search: "hybrid" }, b: { search: "bm25" } },
  { label: "Com vs sem reranker", a: { reranker: true }, b: { reranker: false } },
  { label: "Com vs sem guardrails", a: { guardrails: true }, b: { guardrails: false } },
];

const fresh = (config: RagConfig): Side => ({ config });

export default function Comparar() {
  const [mode, setMode] = useState<CompareMode>("triage");
  const [question, setQuestion] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sides, setSides] = useState<[Side, Side]>([fresh(DEFAULT_CONFIG), fresh({ ...DEFAULT_CONFIG, rag: false })]);
  const [preset, setPreset] = useState(0);
  const [running, setRunning] = useState(false);
  const [slow, setSlow] = useState(false);
  const [ranMode, setRanMode] = useState<CompareMode>(mode); // modo da última comparação, pra renderizar o resultado certo

  const ready = mode === "chat" ? question.trim() : title.trim();

  function update(i: 0 | 1, fn: (s: Side) => Side) {
    setSides((prev) => {
      const next = [...prev] as [Side, Side];
      next[i] = fn(next[i]);
      return next;
    });
  }

  function applyPreset(idx: number) {
    setPreset(idx);
    const p = PRESETS[idx];
    setSides([fresh({ ...DEFAULT_CONFIG, ...p.a }), fresh({ ...DEFAULT_CONFIG, ...p.b })]);
  }

  // Uma chamada só: a API roda as duas configurações em paralelo
  async function compare(e: React.FormEvent) {
    e.preventDefault();
    if (!ready || running) return;
    const configs = sides.map((s) => (mode === "chat" ? { ...s.config, top_k: s.config.top_k ?? CHAT_TOP_K } : s.config));
    const payload: CompareRequest =
      mode === "chat"
        ? { title: question.trim(), body: "", configs, mode, messages: [{ role: "user", content: question.trim() }] }
        : { title, body, configs, mode };

    setSides((prev) => prev.map((s) => fresh(s.config)) as [Side, Side]);
    setRanMode(mode);
    setRunning(true);
    setSlow(false);
    const slowTimer = setTimeout(() => setSlow(true), 12000);
    try {
      const { results } = await postJSON<CompareResponse>("/api/compare", payload);
      ([0, 1] as const).forEach((i) => {
        const r = results?.[i];
        if (!r) update(i, (s) => ({ ...s, error: "A API não devolveu resultado para esta configuração." }));
        else if (isCompareFailure(r)) update(i, (s) => ({ ...s, error: friendlyError(r, r.status) }));
        else if (mode === "chat") update(i, (s) => ({ ...s, chat: r as ChatResult }));
        else update(i, (s) => ({ ...s, triage: r as Triage }));
      });
    } catch (err) {
      const message = (err as Error).message;
      setSides((prev) => prev.map((s) => ({ ...s, error: message })) as [Side, Side]);
    } finally {
      clearTimeout(slowTimer);
      setRunning(false);
      setSlow(false);
    }
  }

  const [ta, tb] = sides.map((s) => (s.chat ?? s.triage)?.timings_ms?.total);
  const faster = ta !== undefined && tb !== undefined && !running ? (ta <= tb ? 0 : 1) : undefined;

  return (
    <div className="app wide">
      <PageHeader title="Comparar" />

      <main className="messages compare">
        <form className="triage-form" onSubmit={compare}>
          <div className="compare-top">
            <div className="segmented" role="radiogroup" aria-label="O que comparar">
              {(["triage", "chat"] as const).map((m) => (
                <button key={m} type="button" role="radio" aria-checked={mode === m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                  {m === "triage" ? "Issue (triagem)" : "Pergunta (chat)"}
                </button>
              ))}
            </div>
            <div className="presets">
              {PRESETS.map((p, idx) => (
                <button key={p.label} type="button" className={`chip${preset === idx ? " on" : ""}`} onClick={() => applyPreset(idx)}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {mode === "chat" ? (
            <textarea rows={3} placeholder="Pergunta enviada pras duas configurações" value={question} onChange={(e) => setQuestion(e.target.value)} />
          ) : (
            <>
              <input placeholder="Título da issue" value={title} onChange={(e) => setTitle(e.target.value)} />
              <textarea rows={4} placeholder="Descrição da issue" value={body} onChange={(e) => setBody(e.target.value)} />
            </>
          )}
          <div className="row">
            <button className="send" disabled={!ready || running}>
              {running ? "Comparando..." : "Comparar"}
            </button>
          </div>
        </form>

        <div className="columns">
          {sides.map((side, i) => (
            <section key={i} className="column">
              <div className="column-head">
                <span className="column-tag">{i === 0 ? "A" : "B"}</span>
                <span className="column-summary">{configSummary(side.config)}</span>
                {faster === i && <span className="pill faster">mais rápida</span>}
              </div>

              <details className="column-config">
                <summary>Ajustar configuração</summary>
                <ConfigForm
                  value={side.config}
                  onChange={(c) => {
                    setPreset(-1);
                    update(i as 0 | 1, (s) => ({ ...s, config: c }));
                  }}
                />
              </details>

              <div className="column-body">
                {running && (
                  <div className="typing">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                    <span className="typing-text">{slow ? "O modelo está ligando, pode levar alguns minutos." : "Comparando..."}</span>
                  </div>
                )}
                {side.error && <div className="meta error">⚠ {side.error}</div>}

                {ranMode === "triage" && side.triage && <TriageResult data={side.triage} config={side.config} />}

                {ranMode === "chat" && side.chat && <ChatAnswer result={side.chat} config={side.config} />}

                {!running && !side.chat && !side.triage && !side.error && (
                  <p className="muted placeholder">A resposta desta configuração aparece aqui.</p>
                )}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}

// Resposta do chat sem streaming, no mesmo visual da página de chat
function ChatAnswer({ result, config }: { result: ChatResult; config: RagConfig }) {
  const removed = result.removed_citations ?? [];
  const mentions = result.removed_mentions ?? [];
  const answer = stripMentions(stripCitations(result.answer ?? "", removed), mentions);
  return (
    <div className="msg assistant">
      <div className={`bubble${result.refused ? " muted-bubble" : ""}`}>
        {result.refused ? answer || REFUSAL : <ReactMarkdown>{answer}</ReactMarkdown>}
      </div>
      {removed.length > 0 && (
        <div className="meta warn-text">Removi {removed.map((n) => `[${n}]`).join(", ")}: trechos que não foram recuperados.</div>
      )}
      {mentions.length > 0 && (
        <div className="meta warn-text">Removi {mentions.join(", ")}: referências que não estão nos trechos.</div>
      )}
      <MetricsBar timings={result.timings_ms} sources={result.sources} config={result.config ?? config} text={answer} />
    </div>
  );
}
