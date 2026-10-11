/** "What this article changed" (Design pass C6): pure helpers, tested in test/recap.test.ts. */

export const BANDS = ["unaware", "heard of", "understands", "can explain"] as const;
export const BAND_LABEL: Record<string, string> = {
  unaware: "New to you",
  "heard of": "Heard of",
  understands: "Understands",
  "can explain": "Can explain",
};

export interface BandMove {
  conceptId: string;
  label: string;
  from: string;
  to: string;
  up: boolean;
}

/** Concepts whose band differs between the snapshot taken when the notes loaded and now. */
export function bandMoves(
  before: Record<string, string>,
  after: Record<string, string>,
  labels: Record<string, string>,
): BandMove[] {
  const rank = (b: string) => BANDS.indexOf(b as (typeof BANDS)[number]);
  return Object.keys(before)
    .filter((id) => after[id] !== undefined && after[id] !== before[id])
    .map((id) => ({
      conceptId: id,
      label: labels[id] ?? id,
      from: before[id] as string,
      to: after[id] as string,
      up: rank(after[id] as string) > rank(before[id] as string),
    }))
    .sort((a, b) => Number(b.up) - Number(a.up) || a.label.localeCompare(b.label));
}

/** Up next items that teach what the reader said they didn't know (by trigger), at most two. */
export function teaching<T extends { triggers: { id: string }[] }>(items: readonly T[], unknown: ReadonlySet<string>): T[] {
  return items.filter((i) => i.triggers.some((t) => unknown.has(t.id))).slice(0, 2);
}
