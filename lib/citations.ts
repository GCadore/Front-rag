// Números [n] citados no texto, sem repetir
export function citedNumbers(text: string) {
  return [...new Set([...text.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])))];
}

// Tira do texto as citações [n] que os guardrails removeram
export function stripCitations(text: string, ids: number[]) {
  return ids.reduce((t, n) => t.replaceAll(` [${n}]`, "").replaceAll(`[${n}]`, ""), text);
}

export const MENTION_MARK = "(referência removida)";

// Menções a issue/PR (#123, links do GitHub) e outras URLs no texto
const MENTION_RE = /https?:\/\/[^\s)\]]+|#\d{2,}/g;

// Mesmo critério da API: a menção precisa aparecer nos trechos recuperados
export function unknownMentions(text: string, haystack: string) {
  return [...new Set(text.match(MENTION_RE) ?? [])].filter((m) => !haystack.includes(m));
}

// Troca no texto as menções que os guardrails removeram pela mesma marca que a API usa
export function stripMentions(text: string, mentions: string[]) {
  return mentions.reduce((t, m) => t.replaceAll(m, MENTION_MARK), text);
}
