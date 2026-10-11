import { describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token" }));

import { draftLine } from "../src/components/profile/Goals";
import { profileApi, type GoalPreview } from "../src/lib/profileApi";
import { previewLines } from "../src/lib/profileFormat";

// Decision 48: topic goals preview with the reader's own words (never saved); interest lines.

const topic: GoalPreview = {
  type: "learning", kind: "topic", label: "Politics", concept_id: null, topic: "politics",
  targets: Array.from({ length: 10 }, (_, i) => ({ concept_id: `c_${i}`, label: `Idea ${i}` })),
}; // prettier-ignore

describe("goal preview line", () => {
  it("names the topic, the reader's words and the number of ideas", () => {
    expect(draftLine(topic, " Indian politics ")).toBe("Goal: understand Politics (Indian politics) · 10 ideas");
    expect(draftLine(topic, "politics")).toBe("Goal: understand Politics · 10 ideas");
    const concept: GoalPreview = { ...topic, kind: "concept", label: "Repo rate", targets: topic.targets.slice(0, 1) };
    expect(draftLine(concept, "repo rate")).toBe("Goal: understand Repo rate · 1 idea");
  });
});

describe("edit preview", () => {
  it("shows interest changes as feed lines", () => {
    const lines = previewLines({
      domains: [], known: [], unknown: [], settings: [], unresolved: [],
      interests: [{ domain: "politics", direction: "more" }, { domain: "sports", direction: "less" }],
    }); // prettier-ignore
    expect(lines).toEqual(["More Politics in your feed", "Less Sports in your feed"]);
  });
});

describe("saving a previewed goal", () => {
  it("sends the previewed ids only, never the typed words", async () => {
    let sent: unknown = null;
    vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
      sent = JSON.parse(String(init.body));
      return new Response("{}", { status: 200 });
    });
    await profileApi.saveLearning(topic);
    vi.unstubAllGlobals();
    expect(sent).toEqual({
      type: "learning_resolved", kind: "topic", concept_id: null, topic: "politics",
      target_ids: topic.targets.map((t) => t.concept_id),
    }); // prettier-ignore
    expect(JSON.stringify(sent)).not.toMatch(/Indian/);
  });
});
