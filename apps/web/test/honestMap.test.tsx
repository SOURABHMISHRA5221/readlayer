// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { Legend, inspectorNote } from "../src/components/profile/KnowledgeMap";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Decision 69 A: the map draws only evidence; a topic's or goal's view also shows ideas with
// nothing recorded, and says so instead of claiming a guessed level.

function legend(scoped: boolean): string[] {
  const host = document.createElement("div");
  act(() => createRoot(host).render(<Legend scoped={scoped} />));
  return [...host.querySelectorAll("li")].map((li) => li.textContent?.trim() ?? "");
}

describe("honest map", () => {
  it("names hollow not-yet dots only in a topic or goal view", () => {
    expect(legend(true)[0]).toBe("Nothing recorded yet");
    expect(legend(false)).not.toContain("Nothing recorded yet");
    expect(legend(false)).toContain("Ready to learn");
  });

  it("never calls a node a guess from the reader's level", () => {
    expect(inspectorNote({ ready: true, band: "unaware", domain: "finance" })).toMatch(/builds on/);
    expect(inspectorNote({ ready: false, band: "unaware", domain: "finance" })).toBe("Nothing recorded yet: read about it, or tell us below.");
    const edited = inspectorNote({ ready: false, band: "understands", domain: "finance" });
    expect(edited).toMatch(/profile/);
    for (const n of ["unaware", "understands"] as const) {
      expect(inspectorNote({ ready: false, band: n, domain: "finance" })).not.toMatch(/estimate from your level/);
    }
  });
});
