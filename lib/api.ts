export const LLM_UNAVAILABLE = "O modelo está ligando ou fora do ar. Tente de novo em alguns instantes.";

// Mensagem amigável pra um corpo de erro da API ({error, message} ou {detail})
export function friendlyError(json: { error?: unknown; message?: unknown; detail?: unknown }, status?: number) {
  if (json.error === "llm_unavailable") return LLM_UNAVAILABLE;
  const detail = typeof json.detail === "string" ? json.detail : undefined;
  const message = typeof json.message === "string" ? json.message : undefined;
  const error = typeof json.error === "string" ? json.error : undefined;
  return message ?? detail ?? error ?? `Erro ${status ?? ""}`.trim();
}

// Lê a mensagem de erro da route do Next ({message}) ou da FastAPI ({detail} ou {error})
export async function errorMessage(res: Response) {
  try {
    const json = await res.json();
    return friendlyError(json, res.status);
  } catch {
    return `Erro ${res.status}`;
  }
}

export async function postJSON<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}
