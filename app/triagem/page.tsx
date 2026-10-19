"use client";

import { useState } from "react";
import ExpectedBox from "@/components/expected-box";
import TriageResult from "@/components/triage-result";
import PageHeader from "@/components/page-header";
import { postJSON } from "@/lib/api";
import { DEMO_EXAMPLES, type DemoExample } from "@/lib/demo-examples";
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
  const [example, setExample] = useState<DemoExample | null>(null);

  // Só preenche o formulário; a triagem continua sendo disparada pelo botão
  function loadExample(id: string) {
    const ex = DEMO_EXAMPLES.find((e) => e.id === id) ?? null;
    setExample(ex);
    setData(null);
    setError("");
    if (ex) {
      setTitle(ex.title);
      setBody(ex.body);
    }
  }

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
        <div className="demo-picker">
          <label htmlFor="demo-example">Carregar exemplo</label>
          <select id="demo-example" value={example?.id ?? ""} onChange={(e) => loadExample(e.target.value)}>
            <option value="">Escolha uma issue real do conjunto de teste…</option>
            {DEMO_EXAMPLES.map((ex) => (
              <option key={ex.id} value={ex.id}>
                {ex.kind === "acerto" ? "✅" : "❌"} {ex.id}: {ex.note}
              </option>
            ))}
          </select>
        </div>

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
        {data && example && <ExpectedBox example={example} result={data} />}
      </main>
    </div>
  );
}
