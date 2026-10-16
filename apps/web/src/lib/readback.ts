/**
 * The readback on onboarding screen 2 (decision 41): one deterministic sentence built from
 * the reader's answers and analogy frame. Pure: same answers, same sentence.
 */

export const READBACK_AFTER = 5;

export interface ReadbackInput {
  liked: string[]; // topic labels of "I'd read this" items, in answer order
  skipped: string[]; // topic labels of "Not for me" items
  frame: string | null; // the analogy frame, e.g. "software"
}

export function listing(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? "";
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

export function readback({ liked, skipped, frame }: ReadbackInput): string {
  // Per topic, likes minus skips: two "Not for me" and one "I'd read this" is still less.
  const net = new Map<string, number>();
  for (const t of liked) net.set(t, (net.get(t) ?? 0) + 1);
  for (const t of skipped) net.set(t, (net.get(t) ?? 0) - 1);
  const more = [...net].filter(([, n]) => n > 0).map(([t]) => t);
  const less = [...net].filter(([, n]) => n < 0).map(([t]) => t);
  const parts: string[] = [];
  if (more.length) parts.push(`more ${listing(more)}`);
  if (less.length) parts.push(`less ${listing(less)}`);
  const reading = parts.length ? `So: ${parts.join(", ")}.` : "So: a mix of everything you picked.";
  // Decision 68 K3: taste only; nothing here claims what the reader knows.
  const how = frame ? ` I'll explain new ideas with ${frame} analogies.` : " I'll explain new ideas in plain words.";
  return reading + how;
}
