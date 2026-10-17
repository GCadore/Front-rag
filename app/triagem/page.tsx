"use client";

import { useState } from "react";
import TriageResult from "@/components/triage-result";
import PageHeader from "@/components/page-header";
import { postJSON } from "@/lib/api";
import { useSettings } from "@/lib/settings";
import type { RagConfig, TriageResult as Triage } from "@/lib/types";


export default function Triagem() {
  const { config } = useSettings();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [data, setData] = useState<Triage | null>(null);
  const [used, setUsed] = useState<RagConfig>(config);
  const [error, setError] = useState("");

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || loading) return;
    setLoading(true);
    setError("");
    setData(null);
    const slowTimer = setTimeout(() => setSlow(true), 12000);
    try {
      // Sem top_k: a API usa o padrão da triagem (10)
      setUsed(config);
      setData(await postJSON<Triage>("/api/triage", { title, body, config }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      clearTimeout(slowTimer);
      setSlow(false);
      setLoading(false);
    }
  }


  return (
    <div className="app">
      <PageHeader title="Triagem" />

      <main className="messages triage">
        <form className="triage-form" onSubmit={run}>
          <input placeholder="Título da issue" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea
            rows={7}
            placeholder="Descrição da issue (cole o corpo como está no GitHub)"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <div className="row">
            <button className="send" disabled={!title.trim() || loading}>
              {loading ? "Analisando..." : "Fazer triagem"}
            </button>
          </div>
          {loading && slow && (
            <div className="status">
              <span className="dot" /> O modelo está ligando, a primeira resposta pode levar alguns minutos.
            </div>
          )}
        </form>

        {error && <div className="error">⚠ {error}</div>}
        {data && <TriageResult data={data} config={used} />}
      </main>
    </div>
  );
}
