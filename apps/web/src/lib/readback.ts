/**
 * Margo's readback on onboarding screen 2 (decision 41): one deterministic sentence built from
 * the reader's answers and analogy frame. Pure: same answers, same sentence.
 */

export const READBACK_AFTER = 5;

export interface ReadbackInput {
  liked: string[]; // topic labels of "I'd read this" items, in answer order
  skipped: string[]; // topic labels of "Not for me" items
  known: string[]; // term labels answered "Yes"
  unknown: string[]; // term labels answered "Not really"
  frame: string | null; // the analogy frame, e.g. "software"
}

const unique = (xs: string[]) => [...new Set(xs)];

export function listing(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? "";
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

export function readback({ liked, skipped, known, unknown, frame }: ReadbackInput): string {
  const more = unique(liked);
  const less = unique(skipped).filter((t) => !more.includes(t));
  const parts: string[] = [];
  if (more.length) parts.push(`more ${listing(more)}`);
  if (less.length) parts.push(`less ${listing(less)}`);
  const reading = parts.length ? `So: ${parts.join(", ")}.` : "So: a mix of everything you picked.";
  const ideas: string[] = [];
  if (known.length) ideas.push(`you know ${listing(unique(known))}`);
  const fresh = unique(unknown);
  if (fresh.length) ideas.push(`${listing(fresh)} ${fresh.length === 1 ? "is" : "are"} new to you`);
  const knowing = ideas.length ? ` ${capital(ideas.join(", and "))}, so I'll explain` : " I'll explain";
  const how = frame ? ` new ideas with ${frame} analogies.` : " new ideas in plain words.";
  return reading + knowing + how;
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
