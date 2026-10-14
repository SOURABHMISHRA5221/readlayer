import type { RecFormat } from "./api";

/**
 * Where a recommendation's original plays, for the link beside "Open in Gloss" / "Open here"
 * (media follow-up B). Named from the URL's host: library items carry a display name in `source`.
 */
export function originalLabel(item: { format: RecFormat; url: string }): string {
  if (item.format === "article") return "Open original";
  const host = hostOf(item.url);
  if (item.format === "video") return host?.endsWith("youtube.com") || host === "youtu.be" ? "Watch on YouTube" : "Watch the original";
  return host ? `Listen on ${appName(host)}` : "Listen to the original";
}

function appName(host: string): string {
  if (host.endsWith("spotify.com")) return "Spotify";
  if (host.endsWith("apple.com")) return "Apple Podcasts";
  return host.replace(/^www\./, "");
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}
