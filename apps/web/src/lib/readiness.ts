import type { FeedItem } from "./feedApi";

/** For you only (decision 60): imported by the ForYouTab chunk, never by the main bundle. */
export const READINESS_BASIS = "Based on the ideas named in the title and summary";

/** The row's readiness line, or null when the item names no idea on the map (or the API is older). */
export function readinessLine(item: Pick<FeedItem, "readiness" | "read_first">): string | null {
  if (item.readiness === "familiar") return "Mostly familiar";
  if (item.readiness === "ready") return "Ready for you";
  if (item.readiness !== "stretch") return null;
  const first = item.read_first ?? [];
  return first.length ? `A stretch: read up on ${first.join(" and ")} first` : "A stretch: many new ideas at once";
}
