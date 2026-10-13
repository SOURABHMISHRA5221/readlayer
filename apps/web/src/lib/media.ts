/**
 * Pure helpers for the media reader (media plan §G, R11): imported only from the reader's lazy
 * media chunk. The YouTube player is driven over postMessage, so no YouTube script is loaded.
 */

export { clock } from "./format";

export const YOUTUBE_ORIGIN = "https://www.youtube-nocookie.com";
// Follow pauses for this long after the reader scrolls on their own.
export const FOLLOW_PAUSE_MS = 5000;

/** Index of the paragraph being spoken at `t` seconds: the last start ≤ t (starts ascending). */
export function paragraphAt(starts: readonly number[], t: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  if (hi < 0 || t < starts[0]!) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid]! <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** The click-to-load embed (R10): no-cookie domain, JS API on for seeking, starts playing. */
export function embedUrl(videoId: string, origin: string, startS: number): string {
  const q = new URLSearchParams({
    enablejsapi: "1",
    origin,
    rel: "0",
    autoplay: "1",
    start: String(Math.max(0, Math.floor(startS))),
  });
  return `${YOUTUBE_ORIGIN}/embed/${encodeURIComponent(videoId)}?${q}`;
}

export function thumbnailUrl(videoId: string): string {
  return `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`;
}

type Command = { event: "listening" } | { event: "command"; func: "seekTo" | "playVideo"; args: unknown[] };

function encode(command: Command): string {
  return JSON.stringify({ ...command, id: 1, channel: "widget" });
}

/** Asks the player to post its state (infoDelivery) to us. Sent after the iframe loads. */
export const LISTENING = encode({ event: "listening" });
export const PLAY = encode({ event: "command", func: "playVideo", args: [] });
export function seekTo(seconds: number): string {
  return encode({ event: "command", func: "seekTo", args: [Math.max(0, seconds), true] });
}

/**
 * The player's current time from one message event, or null: only the YouTube origin, only
 * our own iframe's window, only a JSON infoDelivery that carries a finite currentTime.
 */
export function currentTimeOf(event: Pick<MessageEvent, "origin" | "source" | "data">, player: unknown): number | null {
  if (event.origin !== YOUTUBE_ORIGIN || !player || event.source !== player) return null;
  if (typeof event.data !== "string") return null;
  let data: unknown;
  try {
    data = JSON.parse(event.data);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const { event: kind, info } = data as { event?: unknown; info?: unknown };
  if (kind !== "infoDelivery" && kind !== "initialDelivery") return null;
  const t = info && typeof info === "object" ? (info as { currentTime?: unknown }).currentTime : undefined;
  return typeof t === "number" && Number.isFinite(t) ? t : null;
}

/** Follow keeps the spoken paragraph in view unless switched off or the reader just scrolled. */
export function shouldFollow(on: boolean, lastManualScroll: number, now: number): boolean {
  return on && now - lastManualScroll >= FOLLOW_PAUSE_MS;
}
