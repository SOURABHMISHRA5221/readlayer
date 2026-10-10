import { api, type RecEventType } from "./api";
import type { PersonaKey } from "./personas";

/** Batches recommendation signals: every card seen at once used to send its own request, and
 *  ~20 parallel transactions on the reader's one signals doc contended (30 s latencies, failed
 *  commits) and queued the page's own requests behind them. One request per 400 ms instead. */
export const FLUSH_MS = 400;
export const MAX_BATCH = 50; // the API's per-request limit

type RecEvent = { id: string; type: RecEventType; item_id: string };

const queues = new Map<string, { persona: PersonaKey | null; events: RecEvent[] }>();
let timer: ReturnType<typeof setTimeout> | null = null;

export function queueRecEvent(persona: PersonaKey | null, type: RecEventType, itemId: string): void {
  const key = persona ?? "";
  const queue = queues.get(key) ?? { persona, events: [] };
  queues.set(key, { persona, events: [...queue.events, { id: crypto.randomUUID(), type, item_id: itemId }] });
  if ((queues.get(key)?.events.length ?? 0) >= MAX_BATCH) {
    flushRecEvents();
  } else if (timer === null) {
    timer = setTimeout(flushRecEvents, FLUSH_MS);
  }
}

export function flushRecEvents(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  const pending = [...queues.values()];
  queues.clear();
  for (const { persona, events } of pending) {
    for (let i = 0; i < events.length; i += MAX_BATCH) {
      api.recEvents(persona, events.slice(i, i + MAX_BATCH)).catch(() => {
        // Signals are best-effort; a lost batch only makes ranking slightly less personal.
      });
    }
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushRecEvents);
}
