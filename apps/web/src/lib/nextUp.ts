import type { NextUpChip } from "@readlayer/annotator";

import { api, type RecItem } from "./api";
import type { PersonaKey } from "./personas";
import { recHref } from "./openRec";

/** Decision 67 N3: the card's "Up next" chips come from the article's key ideas. */
export const NEXT_UP_POLL_MS = 1500;
export const NEXT_UP_MAX_POLLS = 8;

export function toChips(items: readonly RecItem[], persona: PersonaKey | null, fromId: string): NextUpChip[] {
  return items.slice(0, 3).map((item) => ({
    id: item.id,
    format: item.format,
    title: item.title,
    source: item.source,
    href: recHref(item, persona, fromId),
    minutes: item.duration_or_read_time ? Math.max(1, Math.round(item.duration_or_read_time / 60)) : null,
  }));
}

/**
 * Fetch the article-basis items once per page, polling briefly while web lookups run. Calls
 * `onItems` with each answer; returns the cancel function.
 */
export function loadNextUp(
  contentId: string,
  persona: PersonaKey | null,
  onItems: (items: RecItem[]) => void,
): () => void {
  const ctrl = new AbortController();
  let polls = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const once = () => {
    api
      .recommendations(contentId, persona, null, ctrl.signal, "article")
      .then((data) => {
        onItems(data.items);
        if (data.pending && polls++ < NEXT_UP_MAX_POLLS) timer = setTimeout(once, NEXT_UP_POLL_MS);
      })
      .catch(() => undefined); // no chips: the card simply has none
  };
  once();
  return () => {
    ctrl.abort();
    clearTimeout(timer);
  };
}

/** `rec_shown` once per chip per page (DESIGN §16.4–16.6: shown-without-click counts). */
export function shownOnce(seen: Set<string>, ids: readonly string[]): string[] {
  const fresh = ids.filter((id) => !seen.has(id));
  for (const id of fresh) seen.add(id);
  return fresh;
}
