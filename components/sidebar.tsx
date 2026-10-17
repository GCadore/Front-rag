"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import ConfigForm from "@/components/config-form";
import { useSettings } from "@/lib/settings";

const LINKS = [
  { href: "/", label: "Chat" },
  { href: "/triagem", label: "Triagem" },
  { href: "/comparar", label: "Comparar" },
];

export default function Sidebar() {
  const path = usePathname();
  const { config, setConfig, sidebarOpen, setSidebarOpen } = useSettings();

  // Fecha a gaveta ao trocar de página
  useEffect(() => setSidebarOpen(false), [path]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
        <div className="brand">Backstage RAG</div>
        <nav className="side-nav">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>
              {l.label}
            </Link>
          ))}
        </nav>

        {path !== "/comparar" && (
          <section className="side-config">
            <h2>Configuração</h2>
            <ConfigForm value={config} onChange={setConfig} />
          </section>
        )}
      </aside>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}
    </>
  );
}
