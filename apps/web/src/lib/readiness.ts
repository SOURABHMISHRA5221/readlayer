import type { FeedItem } from "./feedApi";

/** For you only (decision 60): imported by the ForYouTab chunk, never by the main bundle. */
export const READINESS_BASIS = "Based on the ideas named in the title and summary";
/** Decision 65: a public library article's line comes from its own main ideas. */
export const ARTICLE_BASIS = "Based on the main ideas in the article";

/** The hover text for the row's readiness line (older APIs send no basis: the title rule). */
export function readinessBasis(item: Pick<FeedItem, "readiness_basis">): string {
  return item.readiness_basis === "article" ? ARTICLE_BASIS : READINESS_BASIS;
}

/** The row's readiness line, or null when the item names no idea on the map (or the API is older). */
export function readinessLine(item: Pick<FeedItem, "readiness" | "read_first">): string | null {
  if (item.readiness === "familiar") return "Mostly familiar";
  if (item.readiness === "ready") return "Ready for you";
  if (item.readiness !== "stretch") return null;
  const first = item.read_first ?? [];
  return first.length ? `A stretch: read up on ${first.join(" and ")} first` : "A stretch: many new ideas at once";
}
