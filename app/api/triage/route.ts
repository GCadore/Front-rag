import { mockTriage } from "@/lib/mock-api";
import { isMock, proxy } from "@/lib/proxy";

export const runtime = "nodejs";
export const maxDuration = 300;

// Repassa pra POST ${RAG_API_URL}/triage
export async function POST(req: Request) {
  if (isMock()) return Response.json(await mockTriage(await req.json()));
  return proxy("/triage", req);
}
