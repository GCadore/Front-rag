"use client";

import { useSettings } from "@/lib/settings";

export default function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  const { setSidebarOpen } = useSettings();
  return (
    <header>
      <div className="header-left">
        <button className="menu-btn" aria-label="Abrir menu" onClick={() => setSidebarOpen(true)}>
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>
        <h1>{title}</h1>
      </div>
      {children}
    </header>
  );
}
