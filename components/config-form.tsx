"use client";

import { INDEX_LABELS, SEARCH_LABELS, type RagConfig } from "@/lib/types";

function Segmented<T extends string>({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: T;
  options: Record<T, string>;
  disabled?: boolean;
  onChange: (v: T) => void;
}) {
  return (
    <fieldset className="field" disabled={disabled}>
      <legend>{label}</legend>
      {/* Com mais de 3 opções (Índice) os botões viram uma grade 2x2 pra caber na barra lateral */}
      <div className={`segmented${Object.keys(options).length > 3 ? " grid" : ""}`} role="radiogroup" aria-label={label}>
        {(Object.keys(options) as T[]).map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={value === k}
            className={value === k ? "on" : ""}
            onClick={() => onChange(k)}
          >
            {options[k]}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className={`toggle${disabled ? " disabled" : ""}`}>
      <span>
        {label}
        {hint && <small>{hint}</small>}
      </span>
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" aria-hidden="true" />
    </label>
  );
}

// Usado na barra lateral e em cada coluna da comparação
export default function ConfigForm({ value, onChange }: { value: RagConfig; onChange: (c: RagConfig) => void }) {
  const set = <K extends keyof RagConfig>(k: K, v: RagConfig[K]) => onChange({ ...value, [k]: v });
  const off = !value.rag;
  return (
    <div className="config-form">
      <Toggle label="RAG" hint={value.rag ? "Busca trechos antes de responder" : "O Qwen responde sem contexto"} checked={value.rag} onChange={(v) => set("rag", v)} />
      <Segmented label="Índice" value={value.index} options={INDEX_LABELS} disabled={off} onChange={(v) => set("index", v)} />
      <Segmented label="Busca" value={value.search} options={SEARCH_LABELS} disabled={off} onChange={(v) => set("search", v)} />
      <Toggle label="Reranker" checked={value.reranker} disabled={off} onChange={(v) => set("reranker", v)} />
      <Toggle label="Guardrails" hint="Corte por score e checagem das citações" checked={value.guardrails} disabled={off} onChange={(v) => set("guardrails", v)} />
    </div>
  );
}
