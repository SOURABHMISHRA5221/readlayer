// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GlossInBrowser } from "../src/landing/Extension";
import { Footer } from "../src/landing/Footer";
import { CHIPS } from "../src/landing/formats";
import { FORMATS, PODCAST_CAP_MIN, VIDEO_CAP_MIN } from "../src/landing/formatsFull";
import { HeroStatic } from "../src/landing/Hero";
import { EXTENSION_RELEASE_URL } from "../src/landing/links";
import { WatchAndListen } from "../src/landing/WatchListen";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Vitest runs from apps/web (jsdom rewrites import.meta.url, so it can't anchor the path).
const API = (path: string) => readFileSync(resolve(process.cwd(), "../api", path), "utf8");

/** A `KEY: "value"` line of the production env file. */
function deployEnv(key: string): string {
  const m = API("deploy.env.yaml").match(new RegExp(`^${key}: "([^"]*)"$`, "m"));
  if (!m) throw new Error(`${key} not in deploy.env.yaml`);
  return m[1]!;
}

/** An `name: int = value` default in app/config.py. */
function configDefault(name: string): number {
  const m = API("app/config.py").match(new RegExp(`^\\s+${name}: int = ([\\d_]+)`, "m"));
  if (!m) throw new Error(`${name} not in config.py`);
  return Number(m[1]!.replaceAll("_", ""));
}

const text = (f: (typeof FORMATS)[number]) => `${f.what} ${f.chip} ${f.detail}`;

describe("formats (decision 61, R1/R2)", () => {
  it("the hero's chips are a projection of the full list, same order", () => {
    expect(CHIPS).toEqual(FORMATS.map((f) => ({ label: f.chip, notes: f.notes })));
  });

  it("every format gets notes; none says it is feed-only", () => {
    for (const f of FORMATS) {
      expect(f.notes).toBe(true);
      expect(text(f)).not.toMatch(/in your feed/i);
    }
  });

  it("names short videos, podcasts and the extension, with no Web Store or other-browser claim", () => {
    expect(FORMATS.map((f) => f.chip)).toEqual(["Articles", "Any link", "Short videos", "Podcasts", "Chrome extension"]);
    const ext = FORMATS.find((f) => f.chip === "Chrome extension")!;
    expect(ext.what).toBe("News pages in Chrome");
    for (const f of FORMATS) expect(text(f)).not.toMatch(/web store|firefox|safari|edge/i);
  });

  it("the caps in the copy are production's, and video is switched on there", () => {
    expect(Number(deployEnv("MEDIA_MAX_VIDEO_S")) / 60).toBe(VIDEO_CAP_MIN);
    expect(Number(deployEnv("MEDIA_MAX_AUDIO_S")) / 60).toBe(PODCAST_CAP_MIN);
    expect(configDefault("media_max_video_s") / 60).toBe(VIDEO_CAP_MIN);
    expect(configDefault("media_max_audio_s") / 60).toBe(PODCAST_CAP_MIN);
    expect(deployEnv("MEDIA_VIDEO_ENABLED")).toBe("true");
    expect(deployEnv("MEDIA_AUDIO_ENABLED")).toBe("true");
    const detail = (chip: string) => FORMATS.find((f) => f.chip === chip)!.detail;
    expect(detail("Short videos")).toContain(`up to ${VIDEO_CAP_MIN} minutes`);
    expect(detail("Podcasts")).toContain(`up to ${PODCAST_CAP_MIN} minutes`);
  });

  it("the static hero shows every chip and no longer claims a feed-only format", () => {
    const html = renderToStaticMarkup(<HeroStatic />);
    for (const c of CHIPS) expect(html).toContain(`>${c.label}<`);
    expect(html).not.toMatch(/in your feed/i);
  });
});

async function render(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return {
    host,
    done: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

function expectReleaseLink(a: HTMLAnchorElement | null) {
  expect(a).not.toBeNull();
  expect(a!.getAttribute("href")).toBe(EXTENSION_RELEASE_URL);
  expect(a!.getAttribute("target")).toBe("_blank");
  expect(a!.getAttribute("rel")).toBe("noreferrer");
}

describe("Gloss in your browser (B, R3/R4/R8)", () => {
  it("links the pinned 0.8.2 release (decision 62) and names that version", async () => {
    expect(EXTENSION_RELEASE_URL).toMatch(/\/releases\/tag\/extension-v0\.8\.2$/);
    const { host, done } = await render(<GlossInBrowser />);
    expect(host.querySelector(".lp-ext__get")!.textContent).toBe("Get the extension (v0.8.2)");
    await done();
  });

  it("renders its heading, the access and privacy claims, four install steps and the release link", async () => {
    const { host, done } = await render(<GlossInBrowser />);
    const section = host.querySelector("section[aria-labelledby]")!;
    const title = host.querySelector(`#${section.getAttribute("aria-labelledby")}`)!;
    expect(title.tagName).toBe("H2");
    expect(title.textContent).toBe("Gloss in your browser");
    const copy = section.textContent!;
    expect(copy).toContain("no access to any site until you click it");
    expect(copy).toMatch(/never reads mail, banking, sign-in or private pages, or a page with a password or card field/);
    expect(copy).toMatch(/emails, phone, card, Aadhaar and PAN numbers are removed on your device before the text is sent/i);
    expect(copy).not.toMatch(/web store|firefox|safari/i);

    const steps = [...section.querySelectorAll("ol > li")].map((li) => li.textContent!);
    expect(steps).toHaveLength(4);
    expect(steps[0]).toMatch(/Download gloss-extension\.zip.*unzip it/);
    expect(steps[1]).toMatch(/chrome:\/\/extensions.*Developer mode.*Load unpacked.*folder/);
    expect(steps[2]).toMatch(/account menu.*Use Gloss on any site.*Connect.*demo session works/);
    expect(steps[3]).toMatch(/news article.*Gloss.*Read this page/);

    expectReleaseLink(section.querySelector<HTMLAnchorElement>(`a[href="${EXTENSION_RELEASE_URL}"]`));
    for (const img of section.querySelectorAll("img")) expect(img.getAttribute("alt")).toBeTruthy();
    expect(section.querySelectorAll("img").length).toBeGreaterThanOrEqual(2);
    await done();
  });
});

describe("Watch and listen (C)", () => {
  it("renders its heading, the caps, the transcript caveat and a described still", async () => {
    const { host, done } = await render(<WatchAndListen />);
    const section = host.querySelector("section[aria-labelledby]")!;
    const title = host.querySelector(`#${section.getAttribute("aria-labelledby")}`)!;
    expect(title.tagName).toBe("H2");
    expect(title.textContent).toBe("Watch and listen");
    const copy = section.textContent!;
    expect(copy).toContain(`${VIDEO_CAP_MIN} minutes`);
    expect(copy).toContain(`${PODCAST_CAP_MIN} minutes`);
    expect(copy).toMatch(/transcript is made automatically and can contain errors/);
    expect(copy).toMatch(/longer ones open where they play/i);
    const imgs = section.querySelectorAll("img");
    expect(imgs.length).toBe(1);
    expect(imgs[0]!.getAttribute("alt")).toMatch(/transcript/);
    await done();
  });
});

describe("footer (E)", () => {
  it("has a Get the extension link to the pinned release", async () => {
    const { host, done } = await render(<Footer />);
    const link = [...host.querySelectorAll<HTMLAnchorElement>("footer a")].find((a) => a.textContent === "Get the extension");
    expectReleaseLink(link ?? null);
    await done();
  });
});
