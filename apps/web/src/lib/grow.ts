import { api, type GrowStatus } from "./api";

/** A reader's page whose ideas the caps kept off the map today (M9 part 1). */
export const GROW_RUNNING = "Adding this page's ideas to your map…";
export const GROW_CAPPED =
  "This page's ideas aren't on your map yet. Gloss adds new ones a few pages at a time; open it again tomorrow.";

const RETRY_MS = 5_000;
const WINDOW_MS = 60_000; // the server's growth timeout plus its claim margin

/** POST .../grow until it settles: 202 means another request is growing the page right now.
 *  `waited`: that happened, so the notes may have changed whatever the final answer. */
export async function growUntilDone(id: string, signal: AbortSignal): Promise<{ status: GrowStatus; waited: boolean }> {
  const since = Date.now();
  let waited = false;
  while (!signal.aborted && Date.now() - since < WINDOW_MS) {
    const status = await api.grow(id, signal);
    if (status !== "growing") return { status, waited };
    waited = true;
    await new Promise((r) => setTimeout(r, RETRY_MS));
  }
  return { status: "none", waited };
}
