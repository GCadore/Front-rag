import { mockLabels } from "@/lib/mock-api";
import { isMock, proxy } from "@/lib/proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (isMock()) return Response.json(await mockLabels());
  return proxy("/labels", req);
}
