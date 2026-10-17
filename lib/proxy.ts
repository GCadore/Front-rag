// Repassa a requisição pra API em Python (backend/API_SPEC.md, seção 9).
// A chave fica só no servidor; o browser nunca fala direto com a API.

export const isMock = () => process.env.MOCK_API === "true";

const UNREACHABLE = "Não consegui falar com a API do RAG. Confira se ela está rodando e o RAG_API_URL no .env.local.";

export async function proxy(path: string, req: Request) {
  const base = process.env.RAG_API_URL?.replace(/\/$/, "");
  if (!base) return Response.json({ message: "RAG_API_URL não configurada no .env.local." }, { status: 502 });

  const headers: Record<string, string> = { "x-api-key": process.env.RAG_API_KEY ?? "" };
  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.text();
    headers["Content-Type"] = "application/json";
  }

  let upstream: Response;
  try {
    // req.signal: se o usuário parar no browser, a chamada pra API também é cancelada
    upstream = await fetch(`${base}${path}`, { method: req.method, headers, body, signal: req.signal, cache: "no-store" });
  } catch (err) {
    if ((err as Error).name === "AbortError") return new Response(null, { status: 499 });
    return Response.json({ message: UNREACHABLE }, { status: 502 });
  }

  // Devolve o corpo como veio, o que preserva o SSE do /chat
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
