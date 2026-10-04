import { api, type ReaderEvent, type ReaderEventType } from "./api";
import type { PersonaKey } from "./personas";

/**
 * Reading events (DESIGN §9) batched every 5 s and when the page is hidden, then posted to
 * /v1/events. Each event has its own id, so a retried batch can't count twice. Best effort:
 * a lost batch only makes the reader model slightly less up to date.
 */
const FLUSH_MS = 5000;
const MAX_BATCH = 100;

let queue: { persona: PersonaKey | null; event: ReaderEvent }[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

export function trackEvent(
  type: ReaderEventType,
  conceptId: string | null,
  contentId: string,
  persona: PersonaKey | null,
): void {
  queue = [
    ...queue,
    {
      persona,
      event: { id: crypto.randomUUID(), type, at: new Date().toISOString(), concept_id: conceptId, content_id: contentId },
    },
  ];
  if (queue.length >= MAX_BATCH) void flushEvents();
  else timer ??= setTimeout(() => void flushEvents(), FLUSH_MS);
}

export async function flushEvents(): Promise<void> {
  if (timer) clearTimeout(timer);
  timer = null;
  const pending = queue;
  queue = [];
  // One request per persona (a demo reader can switch persona mid-session).
  const byPersona = new Map<PersonaKey | null, ReaderEvent[]>();
  for (const { persona, event } of pending) byPersona.set(persona, [...(byPersona.get(persona) ?? []), event]);
  await Promise.all(
    [...byPersona].map(([persona, events]) =>
      api.events(persona, events.slice(0, MAX_BATCH)).catch(() => undefined),
    ),
  );
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void flushEvents();
  });
}
