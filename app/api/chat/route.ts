import { mockChat, mockChatStream } from "@/lib/mock-api";
import { isMock, proxy } from "@/lib/proxy";

export const runtime = "nodejs";
// A partida a frio do LLM pode levar alguns minutos
export const maxDuration = 300;

// Repassa pra POST ${RAG_API_URL}/chat; com stream=true a API responde em SSE
export async function POST(req: Request) {
  if (isMock()) {
    const body = await req.json();
    return body.stream === false ? Response.json(await mockChat(body)) : mockChatStream(body);
  }
  return proxy("/chat", req);
}
