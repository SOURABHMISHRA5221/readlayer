/**
 * Decision 50 §F: anything that changes what For you should show (Redo setup finished, a profile
 * edit applied or undone, a learning goal saved or removed, a country change) says so with one
 * window event; a mounted For you tab refetches.
 */
export const FEED_STALE = "rl:feed-stale";

export function markFeedStale(): void {
  window.dispatchEvent(new Event(FEED_STALE));
}
