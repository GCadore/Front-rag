import { errorMessage, friendlyError } from "./api";
import type { ChatDone, ChatMessage, ChatResult, RagConfig, Source, StreamEvent, Timings } from "./types";

// Converte um bloco SSE ("event: x" + "data: {...}") no evento tipado
function parseBlock(block: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comentário / keep-alive
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    const value = i === -1 ? "" : line.slice(i + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(data.join("\n"));
  } catch {
    return null;
  }
  switch (event) {
    case "sources":
      return { type: "sources", sources: (payload.sources ?? []) as Source[] };
    case "token":
      return { type: "token", t: String(payload.t ?? "") };
    case "done":
      return {
        type: "done",
        ...(payload as Partial<ChatDone>),
        timings_ms: (payload.timings_ms ?? { total: 0 }) as Timings,
        refused: !!payload.refused,
      };
    case "error":
      return { type: "error", message: payload.error || payload.message || payload.detail ? friendlyError(payload) : "Erro na API." };
    default:
      return null;
  }
}

// Chama /api/chat com stream=true e entrega cada evento do SSE
export async function streamChat(
  messages: ChatMessage[],
  config: RagConfig,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, config, stream: true }),
    signal,
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  if (!res.body) throw new Error("Resposta vazia da API.");

  // Se a API respondeu em JSON (sem streaming), entrega como se fosse o stream
  if (res.headers.get("content-type")?.includes("application/json")) {
    const r = (await res.json()) as ChatResult;
    onEvent({ type: "sources", sources: r.sources ?? [] });
    if (r.answer) onEvent({ type: "token", t: r.answer });
    onEvent({
      type: "done",
      timings_ms: r.timings_ms,
      refused: r.refused,
      removed_citations: r.removed_citations,
      removed_mentions: r.removed_mentions,
    });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (final: boolean) => {
    // Um "\r" no fim pode ser metade de um "\r\n" que chega no próximo pedaço
    let text = buffer;
    let carry = "";
    if (!final && text.endsWith("\r")) {
      carry = "\r";
      text = text.slice(0, -1);
    }
    const blocks = text.replace(/\r\n?/g, "\n").split("\n\n");
    buffer = final ? "" : blocks.pop()! + carry;
    for (const b of blocks) {
      const e = parseBlock(b);
      if (e) onEvent(e);
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    flush(false);
  }
  buffer += decoder.decode();
  flush(true);
}
