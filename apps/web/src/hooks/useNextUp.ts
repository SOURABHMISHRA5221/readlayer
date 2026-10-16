import type { NextUpChip } from "@readlayer/annotator";
import { useEffect, useRef, type MutableRefObject } from "react";

import type { RecItem } from "../lib/api";
import { loadNextUp, toChips } from "../lib/nextUp";
import type { PersonaKey } from "../lib/personas";

export interface NextUpRefs {
  items: MutableRefObject<RecItem[]>;
  chips: MutableRefObject<NextUpChip[]>;
  /** Chip ids already sent as rec_shown on this page. */
  shown: MutableRefObject<Set<string>>;
}

/**
 * The note card's Up next chips for one page (decision 67 N3). Asked only once the page's notes
 * are `ready` (decision 68 B): a just-opened link is analysed first, and asking before that gets
 * a 409. Read by the annotator at card-open time, so the refs change without a rebuild.
 */
export function useNextUp(articleKey: string | null, persona: PersonaKey | null, ready: boolean): NextUpRefs {
  const items = useRef<RecItem[]>([]);
  const chips = useRef<NextUpChip[]>([]);
  const shown = useRef<Set<string>>(new Set());
  useEffect(() => {
    items.current = [];
    chips.current = [];
    shown.current = new Set();
    if (!articleKey || !ready) return;
    return loadNextUp(articleKey, persona, (found) => {
      items.current = found;
      chips.current = toChips(found, persona, articleKey);
    });
  }, [articleKey, persona, ready]);
  return { items, chips, shown };
}
