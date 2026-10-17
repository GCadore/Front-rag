"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { DEFAULT_CONFIG, normalizeConfig, type RagConfig } from "./types";

const STORAGE_KEY = "rag-config";

interface SettingsContext {
  config: RagConfig;
  setConfig: (c: RagConfig) => void;
  sidebarOpen: boolean; // só importa no celular, onde a barra lateral vira gaveta
  setSidebarOpen: (open: boolean) => void;
}

const Ctx = createContext<SettingsContext | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfigState] = useState<RagConfig>(DEFAULT_CONFIG);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return;
      const raw = JSON.parse(saved);
      const migrated = normalizeConfig(raw);
      setConfigState(migrated);
      // Configuração salva antes da troca de "rerank" para "reranker": regrava no formato novo
      if (raw && "rerank" in raw) localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
    } catch {}
  }, []);

  function setConfig(c: RagConfig) {
    setConfigState(c);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(c));
    } catch {}
  }

  return <Ctx.Provider value={{ config, setConfig, sidebarOpen, setSidebarOpen }}>{children}</Ctx.Provider>;
}

export function useSettings() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSettings precisa estar dentro de SettingsProvider");
  return ctx;
}
