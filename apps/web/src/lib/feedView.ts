import type { FeedItem, FeedResponse } from "./feedApi";

/** For you page logic kept pure so it can be tested without a DOM (M7.5). */
export const REASK_MS = 3000;
export const MAX_REASKS = 3;

/** Delay before asking again while searches are still running, or null to stop. */
export function reaskDelay(pending: boolean, attempt: number): number | null {
  return pending && attempt < MAX_REASKS ? REASK_MS : null;
}

/** The status line while picks are still arriving; it changes once re-asks are used up. */
export function pendingNote(pending: boolean, attempt: number): string | null {
  if (!pending) return null;
  return attempt < MAX_REASKS ? "Still gathering a few picks…" : "A few picks are still on the way. Check back in a minute.";
}

/** The demo note (decision 38): prepared in advance, may be dated, sign in for a live feed. */
export function snapshotNote(feed: Pick<FeedResponse, "snapshot" | "prepared_at">, date: (iso: string) => string): string | null {
  if (!feed.snapshot) return null;
  const when = feed.prepared_at ? ` (${date(feed.prepared_at)})` : "";
  return `Picks prepared in advance for this demo${when}, so some may be dated. Sign in with Google for a live feed.`;
}

export function visibleItems(items: readonly FeedItem[], dismissed: ReadonlySet<string>): FeedItem[] {
  return items.filter((i) => !dismissed.has(i.id));
}
