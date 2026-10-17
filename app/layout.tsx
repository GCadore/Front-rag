import type { Metadata } from "next";
import Sidebar from "@/components/sidebar";
import { SettingsProvider } from "@/lib/settings";
import "./globals.css";

export const metadata: Metadata = {
  title: "Backstage RAG",
  description: "Chat com IA sobre os documentos indexados no Modal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <SettingsProvider>
          <div className="shell">
            <Sidebar />
            <div className="main">{children}</div>
          </div>
        </SettingsProvider>
      </body>
    </html>
  );
}
