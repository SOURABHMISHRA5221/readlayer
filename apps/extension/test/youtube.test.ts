import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { youtubeWatchUrl } from "../src/youtube";

// The API's own cases (apps/api/tests/test_media_urls.py reads the same file), so Open in Gloss
// offers exactly the links the API opens as a video (decision 62).
const fixture = JSON.parse(
  readFileSync(resolve(__dirname, "../../api/tests/fixtures/youtube_urls.json"), "utf8"),
) as { canonical: string; videos: string[]; not_videos: string[] };

describe("youtubeWatchUrl", () => {
  it.each(fixture.videos)("maps %s to the one canonical watch URL", (url) => {
    expect(youtubeWatchUrl(url)).toBe(fixture.canonical);
  });
  it.each(fixture.not_videos)("is null for %s", (url) => {
    expect(youtubeWatchUrl(url)).toBeNull();
  });
  it("is null for no URL (a tab without one)", () => {
    expect(youtubeWatchUrl(undefined)).toBeNull();
  });
});
