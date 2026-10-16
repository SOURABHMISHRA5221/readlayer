/** A page loaded before a deploy asks for code files the new build no longer has (decision 69 E:
 *  hashed assets are 404 after a deploy). Vite fires `vite:preloadError`; reload once to get the
 *  new build. A flag in sessionStorage stops a reload loop when the files are truly missing. */

const KEY = "gloss:stale-reload";
const WINDOW_MS = 60_000;

export function shouldReload(storage: Pick<Storage, "getItem" | "setItem"> | null, now: number): boolean {
  if (!storage) return false; // nowhere to remember the reload: never risk a loop
  try {
    const last = Number(storage.getItem(KEY) ?? 0);
    if (now - last < WINDOW_MS) return false;
    storage.setItem(KEY, String(now));
    return true;
  } catch {
    return false; // storage blocked: never risk a loop
  }
}

export function reloadOnStaleChunk(target: Window = window): void {
  target.addEventListener("vite:preloadError", (event) => {
    let storage: Storage | null = null;
    try {
      storage = target.sessionStorage;
    } catch {
      storage = null;
    }
    if (shouldReload(storage, Date.now())) {
      event.preventDefault();
      target.location.reload();
    }
  });
}
