import { api, opensHere, type RecItem } from "./api";
import { personaParam, type PersonaKey } from "./personas";
import { navigate, withParams } from "./router";

/**
 * Opening a recommendation, shared by the end-of-article Up next and the card chips (decision
 * 67 N3): a library item opens in the reader; a web item Gloss can open (`open_here`) is
 * brought in and opened; anything else opens at its source in a new tab.
 */
export function recReaderHref(contentId: string, persona: PersonaKey | null, recId: string, fromId: string): string {
  return withParams(new URL(`/read/${contentId}`, window.location.origin), {
    persona: personaParam(persona),
    rec: recId,
    from: fromId,
  });
}

/** Where the item's link points (keyboard, middle-click, copy link). */
export function recHref(item: RecItem, persona: PersonaKey | null, fromId: string): string {
  return item.kind === "library" && item.content_id ? recReaderHref(item.content_id, persona, item.id, fromId) : item.url;
}

/** Open it; falls back to the source in a new tab if bringing a web page in fails. */
export async function openRec(item: RecItem, persona: PersonaKey | null, fromId: string): Promise<void> {
  if (item.kind === "library" && item.content_id) {
    navigate(recReaderHref(item.content_id, persona, item.id, fromId));
    window.scrollTo(0, 0);
    return;
  }
  if (item.kind === "web" && opensHere(item)) {
    try {
      const { content_id } = await api.openWeb(item.url);
      navigate(recReaderHref(content_id, persona, item.id, fromId));
      window.scrollTo(0, 0);
      return;
    } catch {
      // Couldn't be brought in: the original still works.
    }
  }
  window.open(item.url, "_blank", "noopener,noreferrer");
}
