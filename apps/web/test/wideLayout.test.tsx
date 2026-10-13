// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token", signOutUser: async () => undefined, useIsDemo: () => false }));

import { Sidebar } from "../src/components/library/Sidebar";
import { Quiet } from "../src/components/Quiet";
import type { PersonaKey } from "../src/lib/personas";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Wide layout (decision 45): the sidebar's two groups and the lazy "Your map this week".

let paths: string[] = [];
let root: Root;
let host: HTMLDivElement;

const node = (id: string, domain: string, rose = false) => ({
  id, label: id, domain, band: "understands", ready: false, goal: false, weight: 0.5, definition: "", recent: [], rose_this_week: rose,
});
const OVERVIEW = { view: "overview", domains: ["finance", "policy"], nodes: [node("repo_rate", "finance", true), node("gst", "policy")], edges: [] };

function stub(width: number, overview: unknown | "fail" = OVERVIEW) {
  paths = [];
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return { matches: width >= min, media: query, addEventListener: () => undefined, removeEventListener: () => undefined };
  });
  vi.stubGlobal("fetch", async (url: string) => {
    const u = new URL(url, "http://localhost");
    paths.push(u.pathname + u.search);
    if (u.pathname === "/v1/me/graph") {
      return overview === "fail" ? new Response("{}", { status: 500 }) : new Response(JSON.stringify(overview), { status: 200 });
    }
    return new Response(JSON.stringify(u.pathname === "/v1/me/goals" ? [] : {}), { status: 200 });
  });
}

/** The panel is a lazy chunk and then a request: wait until the sidebar stops loading. */
async function settle() {
  for (let i = 0; i < 100; i++) {
    await act(async () => new Promise((r) => setTimeout(r, 5)));
    if (i > 2 && !host.querySelector(".weekmap__skeleton") && !host.textContent?.includes("Loading…")) return;
  }
}

async function mount(props: { persona?: PersonaKey | null; demo?: boolean; settled?: boolean } = {}) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <Sidebar persona={props.persona ?? null} demo={props.demo ?? false} topics={["finance", "policy"]} settled={props.settled ?? true} onTopic={() => undefined} />,
    ),
  );
  await settle();
}

const headings = () => [...host.querySelectorAll("h2")].map((h) => h.textContent);
const graphCalls = () => paths.filter((p) => p.startsWith("/v1/me/graph"));

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
});

describe("an optional part that fails to load", () => {
  const Broken = (): never => {
    throw new Error("chunk failed");
  };
  it("shows its fallback and leaves the rest of the page standing", async () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined); // React reports the caught error
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () =>
      root.render(
        <>
          <p>article</p>
          <Quiet fallback={<span>no map</span>}>
            <Broken />
          </Quiet>
          <Quiet>
            <Broken />
          </Quiet>
        </>,
      ),
    );
    expect(host.textContent).toBe("articleno map");
    quiet.mockRestore();
  });
});

describe("library sidebar on a wide screen", () => {
  it("has no map block and asks for no map while the sidebar is stacked (960px and under)", async () => {
    stub(960);
    await mount();
    expect(headings()).toEqual(["Read any link", "Topics for you", "Your goals"]);
    expect(graphCalls()).toEqual([]);
  });

  it("orders its blocks tools first, then the reader's map and goals, in two groups", async () => {
    stub(1280);
    await mount();
    expect(headings()).toEqual(["Read any link", "Topics for you", "Your map this week", "Your goals"]);
    const groups = [...host.querySelectorAll(".side__col")].map((c) => [...c.querySelectorAll("h2")].map((h) => h.textContent));
    expect(groups).toEqual([["Read any link", "Topics for you"], ["Your map this week", "Your goals"]]);
    expect(graphCalls()).toEqual(["/v1/me/graph?view=overview"]);
    expect(host.querySelectorAll(".weekmap__tile")).toHaveLength(2);
    expect(host.querySelector(".weekmap__line")?.textContent).toBe("1 idea moved up this week: repo_rate");
    const labels = [...host.querySelectorAll(".weekmap__tile svg")].map((s) => s.getAttribute("aria-label"));
    expect(labels).toEqual(["Finance: 1 idea moved up this week", "Policy: no change this week"]);
    expect(host.querySelector(".weekmap")?.textContent).not.toMatch(/\d+ ideas?(?! moved)/); // no per-topic totals
  });

  it("waits for the library's first answer before asking for the map", async () => {
    stub(1440);
    await mount({ settled: false }); // stays on its placeholder for as long as we wait
    expect(graphCalls()).toEqual([]);
    expect(host.querySelector(".weekmap__skeleton")).not.toBeNull();
  });

  it("says so when the map doesn't load, and keeps the rest", async () => {
    stub(1280, "fail");
    await mount();
    expect(host.querySelector(".side__block--week")?.textContent).toContain("Your map didn't load.");
    expect(headings()).toContain("Your goals");
    expect(host.querySelector("#anylink-side")).not.toBeNull();
  });

  it("names the demo persona and keeps it on the link to the full map", async () => {
    stub(1280);
    await mount({ persona: "trader", demo: true });
    expect(headings()).toContain("Markets trader's map this week");
    expect(graphCalls()).toEqual(["/v1/me/graph?view=overview&persona=trader"]);
    expect(host.querySelector(".weekmap__link")?.getAttribute("href")).toBe("/profile?persona=trader#kmap-title");
  });

  it("tells a new reader the map fills in as they read", async () => {
    stub(1280, { view: "overview", domains: [], nodes: [], edges: [] });
    await mount();
    expect(host.querySelector(".side__block--week")?.textContent).toContain("Your map fills in as you read.");
  });
});
