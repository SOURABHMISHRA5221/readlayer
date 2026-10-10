import { api, type ReaderEvent, type ReaderEventType } from "./api";
import type { PersonaKey } from "./personas";

/**
 * Reading events (DESIGN §9) batched every 5 s and when the page is hidden, then posted to
 * /v1/events. Each event has its own id, so a retried batch can't count twice: a batch that
 * fails is queued again once, then dropped (it only makes the reader model slightly staler).
 */
const FLUSH_MS = 5000;
const MAX_BATCH = 100;

interface Queued {
  persona: PersonaKey | null;
  event: ReaderEvent;
  retried: boolean;
}

export interface EventDetail {
  paragraph_id?: string;
  words?: number;
  ms?: number;
}

let queue: Queued[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
// Called before a hide flush so signals still accumulating (dwell) make the batch.
const beforeFlush = new Set<() => void>();

export function trackEvent(
  type: ReaderEventType,
  conceptId: string | null,
  contentId: string,
  persona: PersonaKey | null,
  detail: EventDetail = {},
): void {
  const event: ReaderEvent = {
    id: crypto.randomUUID(),
    type,
    at: new Date().toISOString(),
    concept_id: conceptId,
    content_id: contentId,
    ...detail,
  };
  enqueue([{ persona, event, retried: false }]);
}

function enqueue(items: Queued[]): void {
  queue = [...queue, ...items];
  if (queue.length >= MAX_BATCH) void flushEvents();
  else timer ??= setTimeout(() => void flushEvents(), FLUSH_MS);
}

/** Register a hook run before each page-hide flush; returns its unregister function. */
export function onBeforeFlush(hook: () => void): () => void {
  beforeFlush.add(hook);
  return () => beforeFlush.delete(hook);
}

export async function flushEvents(): Promise<void> {
  if (timer) clearTimeout(timer);
  timer = null;
  const pending = queue.slice(0, MAX_BATCH);
  queue = queue.slice(MAX_BATCH);
  if (queue.length) timer = setTimeout(() => void flushEvents(), FLUSH_MS);
  // One request per persona (a demo reader can switch persona mid-session).
  const byPersona = new Map<PersonaKey | null, Queued[]>();
  for (const item of pending) byPersona.set(item.persona, [...(byPersona.get(item.persona) ?? []), item]);
  await Promise.all(
    [...byPersona].map(([persona, items]) =>
      api
        .events(
          persona,
          items.map((i) => i.event),
        )
        .catch(() => {
          const again = items.filter((i) => !i.retried).map((i) => ({ ...i, retried: true }));
          if (again.length) enqueue(again);
        }),
    ),
  );
}

function flushOnHide(): void {
  beforeFlush.forEach((hook) => hook());
  void flushEvents();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushOnHide();
  });
  window.addEventListener("pagehide", flushOnHide);
}
