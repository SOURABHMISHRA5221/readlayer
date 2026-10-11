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

/** Band changes minus concepts the reader answered "Not really" to: those get one row of their
 *  own ("Next on your path"), never two. */
export function movesExcept<T extends BandMove>(moves: readonly T[], answered: ReadonlySet<string>): T[] {
  return moves.filter((m) => !answered.has(m.conceptId));
}

/** Up next items that teach what the reader said they didn't know (by trigger), at most two. */
export function teaching<T extends { triggers: { id: string }[] }>(items: readonly T[], unknown: ReadonlySet<string>): T[] {
  return items.filter((i) => i.triggers.some((t) => unknown.has(t.id))).slice(0, 2);
}

/** What the recap offers next: items that teach an unknown concept, else Up next's top two under
 *  a neutral label (never "teaches X"). */
export function nextReads<T extends { triggers: { id: string }[] }>(
  items: readonly T[],
  unknown: ReadonlySet<string>,
): { items: T[]; teaches: boolean } {
  const taught = teaching(items, unknown);
  return taught.length ? { items: taught, teaches: true } : { items: items.slice(0, 2), teaches: false };
}

/** The recap's labels for one page view (an article, persona and density). */
export interface RecapView {
  key: string;
  labels: Readonly<Record<string, string>>;
}

/**
 * Adds a notes response's concepts to the view's labels (decision 46d): within one view they only
 * accumulate, so a refetch after a "Know this?" answer never loses the prompt's concept (its "Yes"
 * stays a band move with its Undo) nor resets the "before" snapshot. A new view starts fresh.
 */
export function mergeRecapView(
  prev: RecapView,
  key: string,
  annotations: readonly { concept_id?: string | null; label: string }[],
  extras: readonly { kind: string; concept_id?: string; label?: string }[],
): RecapView {
  const labels: Record<string, string> = prev.key === key ? { ...prev.labels } : {};
  let changed = prev.key !== key;
  const add = (id: string | null | undefined, label: string | undefined) => {
    if (!id || !label || labels[id]) return;
    labels[id] = label;
    changed = true;
  };
  for (const a of annotations) add(a.concept_id, a.label);
  for (const x of extras) if (x.kind === "prompt") add(x.concept_id, x.label);
  return changed ? { key, labels } : prev;
}
