import type { ApiOp, ApiReply } from "./messages";

// M9 part 1: a reader's stored page that missed concept growth (the day's caps ran out) grows when
// it is reopened, then its notes reload. Pure apart from the injected API call, sleep and clock.

export type GrowStatus = "none" | "capped" | "grown";

export const GROW_CAPPED =
  "This page's ideas aren't on your map yet. Gloss adds new ones a few pages at a time; open it again tomorrow.";

const RETRY_MS = 5_000;
const WINDOW_MS = 60_000; // the server's growth timeout plus its claim margin

/** The API marks the page (`grow_pending`). The detail is read after any analysis here, so it
 *  already says whether that analysis was short of growth slots. */
export function shouldGrow(detail: { grow_pending?: boolean }): boolean {
  return detail.grow_pending === true;
}

/** POST .../grow until it settles (202: another request is growing it). Errors end it quietly:
 *  the page keeps the notes it has. */
export async function growUntilDone(
  id: string,
  api: (op: Extract<ApiOp, { op: "grow" }>) => Promise<ApiReply>,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
  now: () => number = Date.now,
): Promise<GrowStatus> {
  const until = now() + WINDOW_MS;
  while (now() < until) {
    const res = await api({ op: "grow", id });
    if (!res.ok) return "none";
    if (res.status !== 202) return ((res.data as { status?: GrowStatus }).status ?? "none") as GrowStatus;
    await sleep(RETRY_MS);
  }
  return "none";
}

export function finalToast(resolved: number, grow: GrowStatus | null): string {
  if (resolved) return `Notes are ready: ${resolved} on this page.`;
  return grow === "capped" ? GROW_CAPPED : "Nothing new for you on this page.";
}
