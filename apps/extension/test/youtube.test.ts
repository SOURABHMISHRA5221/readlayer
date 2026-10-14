import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { VIDEO_HINT, VIDEO_MAX_MINUTES, youtubeWatchUrl } from "../src/youtube";

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

describe("the popup's video hint", () => {
  it("states the API's production video cap", () => {
    const env = readFileSync(resolve(__dirname, "../../api/deploy.env.yaml"), "utf8");
    const seconds = Number(/^MEDIA_MAX_VIDEO_S:\s*"?(\d+)"?\s*$/m.exec(env)?.[1]);
    expect(VIDEO_MAX_MINUTES * 60).toBe(seconds);
    expect(VIDEO_HINT).toContain(`Up to ${VIDEO_MAX_MINUTES} minutes`);
  });
});
