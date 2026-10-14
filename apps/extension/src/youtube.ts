/**
 * Open in Gloss on YouTube (decision 62): the one canonical watch URL for a video page, or null.
 * Mirrors the API's `media/urls.py` `classify` for YouTube (the shared fixture checks both), and
 * keeps only the video id: no playlist, time, `si` or other parameter ever leaves the browser.
 */

/** The API's video cap (`MEDIA_MAX_VIDEO_S` 600 in apps/api/deploy.env.yaml; a test checks). */
export const VIDEO_MAX_MINUTES = 10;
export const VIDEO_HINT = `Opens this video in Gloss with a transcript and notes. Up to ${VIDEO_MAX_MINUTES} minutes.`;

const HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com"]);
const SHORT_HOST = "youtu.be";
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

export function youtubeWatchUrl(url: string | undefined): string | null {
  let parts: URL;
  try {
    parts = new URL((url ?? "").trim());
  } catch {
    return null;
  }
  const host = parts.hostname.toLowerCase().replace(/\.$/, "");
  if (!["http:", "https:"].includes(parts.protocol) || parts.username || parts.password) return null;
  if (!HOSTS.has(host) && host !== SHORT_HOST) return null;
  const id = videoId(host, parts);
  return id ? `https://www.youtube.com/watch?v=${id}` : null;
}

function videoId(host: string, parts: URL): string | null {
  const segments = parts.pathname.split("/").filter(Boolean);
  let candidate: string | undefined;
  if (host === SHORT_HOST) candidate = segments.length === 1 ? segments[0] : undefined;
  else if (segments.length === 1 && segments[0] === "watch") {
    const values = parts.searchParams.getAll("v").filter(Boolean);
    candidate = values.length === 1 ? values[0] : undefined;
  } else if (segments.length === 2 && (segments[0] === "shorts" || segments[0] === "embed")) {
    candidate = segments[1];
  }
  return candidate && VIDEO_ID.test(candidate) ? candidate : null;
}
