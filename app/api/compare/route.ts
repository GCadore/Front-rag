import { mockCompare } from "@/lib/mock-api";
import { isMock, proxy } from "@/lib/proxy";

export const runtime = "nodejs";
export const maxDuration = 300;

// Repassa pra POST ${RAG_API_URL}/compare, que roda as configurações em paralelo
export async function POST(req: Request) {
  if (isMock()) return Response.json(await mockCompare(await req.json()));
  return proxy("/compare", req);
}
