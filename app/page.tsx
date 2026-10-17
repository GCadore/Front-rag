"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import MetricsBar from "@/components/metrics-bar";
import PageHeader from "@/components/page-header";
import { useSettings } from "@/lib/settings";
import { stripCitations, stripMentions } from "@/lib/citations";
import { streamChat } from "@/lib/stream-chat";
import { CHAT_TOP_K, REFUSAL, type ChatMessage, type RagConfig, type Source, type StreamEvent, type Timings } from "@/lib/types";

interface UIMessage extends ChatMessage {
  sources?: Source[];
  error?: string;
  notice?: string; // a API recusou (guardrail de entrada); mostra o texto da recusa
  removed?: number[]; // citações [n] removidas por não existirem
  removedMentions?: string[]; // issues, PRs e links fora dos trechos
  time?: number;
  timings?: Timings;
  config?: RagConfig; // configuração usada nesta resposta
}

const hhmm = (t?: number) =>
  t ? new Date(t).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";


const STORAGE_KEY = "rag-chat-history";
const SUGGESTIONS = ["Sobre o que são esses documentos?", "Resuma os pontos principais", "Como faço a instalação?"];

export default function Chat() {
  const { config } = useSettings();
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // O campo cresce com o texto, até o limite do CSS
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);


  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) setMessages(JSON.parse(saved));
    } catch {}
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {}
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function updateLast(fn: (m: UIMessage) => UIMessage) {
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || loading) return;

    const now = Date.now();
    const history: UIMessage[] = [...messages, { role: "user", content: question, time: now }];
    const used: RagConfig = { ...config, top_k: config.top_k ?? CHAT_TOP_K };
    setMessages([...history, { role: "assistant", content: "", time: now, config: used }]);
    setInput("");
    setLoading(true);
    setSlow(false);
    // Se demorar, provavelmente é partida a frio do container
    const slowTimer = setTimeout(() => setSlow(true), 12000);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // Respostas recusadas ou com erro ficam sem texto; não vão no histórico
      const payload = history.filter((m) => m.content.trim()).map(({ role, content }) => ({ role, content }));
      await streamChat(
        payload,
        used,
        (event: StreamEvent) => {
          if (event.type === "sources") updateLast((m) => ({ ...m, sources: event.sources }));
          if (event.type === "token") {
            clearTimeout(slowTimer);
            setSlow(false);
            updateLast((m) => ({ ...m, content: m.content + event.t, time: m.content ? m.time : Date.now() }));
          }
          if (event.type === "done")
            updateLast((m) => {
              const removed = event.removed_citations ?? [];
              const base = { ...m, timings: event.timings_ms, time: m.time ?? Date.now() };
              // Recusa: a API nem chamou o modelo; o texto vem nos tokens ou no próprio done
              if (event.refused) return { ...base, content: "", notice: m.content.trim() || event.answer || REFUSAL };
              const mentions = event.removed_mentions ?? [];
              const content = stripMentions(stripCitations(m.content, removed), mentions);
              return { ...base, content, removed, removedMentions: mentions };
            });
          if (event.type === "error") updateLast((m) => ({ ...m, error: event.message }));
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        updateLast((m) => ({ ...m, error: (err as Error).message }));
      }
    } finally {
      clearTimeout(slowTimer);
      setLoading(false);
      setSlow(false);
      abortRef.current = null;
    }
  }

  function reset() {
    abortRef.current?.abort();
    setMessages([]);
  }

  return (
    <div className="app">
      <PageHeader title="Chat">
        {messages.length > 0 && (
          <button className="ghost" onClick={reset}>
            Nova conversa
          </button>
        )}
      </PageHeader>

      <main className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <h2>Pergunte sobre os documentos</h2>
            <p>As respostas usam os trechos encontrados no Chroma e mostram as fontes.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="ghost" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => {
          const isLast = i === messages.length - 1;
          const typing = isLast && loading && !m.content && !m.notice;

          if (m.role === "user")
            return (
              <div key={i} className={`msg user${i === messages.length - 2 && loading ? " enter" : ""}`}>
                <div className="bubble">{m.content}</div>
              </div>
            );

          return (
            <div key={i} className={`msg assistant${isLast && loading ? " appear" : ""}`}>
              <div className="meta">
                Backstage RAG <span className="sep">•</span> {hhmm(m.time)}
              </div>

              <div className={`bubble${m.notice ? " muted-bubble" : ""}`}>
                {typing ? (
                  <span className="typing">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                    {slow && <span className="typing-text">O modelo está ligando, pode levar alguns minutos.</span>}
                  </span>
                ) : m.notice ? (
                  m.notice
                ) : (
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                )}
              </div>

              {m.removed && m.removed.length > 0 && (
                <div className="meta warn-text">
                  Removi {m.removed.map((n) => `[${n}]`).join(", ")}: trechos que não foram recuperados.
                </div>
              )}
              {m.removedMentions && m.removedMentions.length > 0 && (
                <div className="meta warn-text">
                  Removi {m.removedMentions.join(", ")}: referências que não estão nos trechos.
                </div>
              )}
              {m.error && <div className="meta error">⚠ {m.error}</div>}

              <MetricsBar timings={m.timings} sources={m.sources} config={m.config} text={m.content} />
            </div>
          );
        })}
        <div ref={bottomRef} />
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div className="box">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            placeholder="Escreva sua pergunta..."
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <div className="box-actions">
            {loading ? (
              <button type="button" className="round send-round" aria-label="Parar" onClick={() => abortRef.current?.abort()}>
                <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                  <rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor" />
                </svg>
              </button>
            ) : (
              <button type="submit" className="round send-round" aria-label="Enviar" disabled={!input.trim()}>
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
