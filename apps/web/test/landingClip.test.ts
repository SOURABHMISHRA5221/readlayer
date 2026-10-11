// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClipView, MAX_ZOOM, zoomFor } from "../src/landing/Clip";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// One IntersectionObserver stand-in: every observed element counts as on screen.
class OnScreen {
  constructor(private cb: IntersectionObserverCallback) {}
  observe(el: Element) {
    this.cb([{ isIntersecting: true, target: el } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
  disconnect() {}
}

const props = { name: "clip-note", label: "tapping a highlighted term opens its note", width: 1440, height: 900 };
const focus = { x: 0.5, y: 0.3, w: 0.3, h: 0.4 };

let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  vi.stubGlobal("IntersectionObserver", OnScreen);
  HTMLMediaElement.prototype.load = vi.fn();
  HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  HTMLMediaElement.prototype.pause = vi.fn();
});
afterEach(() => {
  host.remove();
  vi.unstubAllGlobals();
});

describe("landing clips", () => {
  it("under reduced motion, only the poster: no video and no pause button", async () => {
    const root = createRoot(host);
    await act(async () => root.render(createElement(ClipView, { ...props, reducedMotion: true })));
    expect(host.querySelector("video")).toBeNull();
    expect(host.querySelector("button")).toBeNull();
    expect(host.querySelector("img")?.getAttribute("src")).toBe("/landing/clip-note-poster.webp");
    await act(async () => root.unmount());
  });

  it("loads only when near, plays on screen, and the Pause button pauses and resumes it", async () => {
    const root = createRoot(host);
    await act(async () => root.render(createElement(ClipView, { ...props, reducedMotion: false })));
    const video = host.querySelector("video")!;
    expect(video.muted).toBe(true);
    expect(video.loop).toBe(true);
    expect(video.getAttribute("aria-hidden")).toBe("true");
    const sources = [...video.querySelectorAll("source")];
    expect(sources).toHaveLength(4);
    // Small screens first (older browsers ignore media and play the first source).
    expect(sources.slice(0, 2).map((x) => x.getAttribute("media"))).toEqual(["(max-width: 1023px)", "(max-width: 1023px)"]);
    expect(sources[0]!.getAttribute("src")).toBe("/landing/clip-note-1x.webm");
    expect(sources[2]!.getAttribute("media")).toBeNull();
    expect(video.getAttribute("poster")).toBe("/landing/clip-note-poster.webp"); // set once near
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    const button = host.querySelector<HTMLButtonElement>("button")!;
    expect(button.getAttribute("aria-label")).toContain(props.label);
    expect(button.getAttribute("aria-pressed")).toBe("false");
    await act(async () => button.click());
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();

    vi.mocked(HTMLMediaElement.prototype.play).mockClear();
    await act(async () => button.click());
    expect(button.getAttribute("aria-pressed")).toBe("false");
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    await act(async () => root.unmount());
  });

  it("zooms toward the action only while playing; Pause stops it", async () => {
    const root = createRoot(host);
    await act(async () => root.render(createElement(ClipView, { ...props, focus, reducedMotion: false })));
    const video = host.querySelector("video")!;
    const tile = host.querySelector<HTMLElement>(".lp-clip")!;
    Object.defineProperty(video, "duration", { configurable: true, value: 4 });
    Object.defineProperty(video, "currentTime", { configurable: true, writable: true, value: 2 });
    await act(async () => video.dispatchEvent(new Event("timeupdate")));
    expect(tile.classList.contains("lp-clip--zoomed")).toBe(true);
    expect(Number(tile.style.getPropertyValue("--clip-zoom"))).toBeLessThanOrEqual(MAX_ZOOM);
    await act(async () => host.querySelector<HTMLButtonElement>(".lp-clip__toggle")!.click());
    expect(tile.classList.contains("lp-clip--zoomed")).toBe(false);
    expect(tile.getAnimations?.() ?? []).toHaveLength(0);
    // Near the loop's end the zoom eases out again.
    await act(async () => host.querySelector<HTMLButtonElement>(".lp-clip__toggle")!.click());
    video.currentTime = 3.9;
    await act(async () => video.dispatchEvent(new Event("timeupdate")));
    expect(tile.classList.contains("lp-clip--zoomed")).toBe(false);
    await act(async () => root.unmount());
  });

  it("never zooms under reduced motion, and never past 1.15×", async () => {
    const root = createRoot(host);
    await act(async () => root.render(createElement(ClipView, { ...props, focus, reducedMotion: true })));
    expect(host.querySelector(".lp-clip--zoomed, .lp-clip__spot")).toBeNull();
    await act(async () => root.unmount());
    expect(zoomFor({ x: 0, y: 0, w: 0.05, h: 0.05 })).toBe(MAX_ZOOM);
    expect(zoomFor({ x: 0, y: 0, w: 1, h: 1 })).toBe(1);
  });

  it("if autoplay is blocked, the poster offers Tap to play", async () => {
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.reject(new DOMException("blocked", "NotAllowedError")));
    const root = createRoot(host);
    await act(async () => root.render(createElement(ClipView, { ...props, reducedMotion: false })));
    const play = host.querySelector<HTMLButtonElement>(".lp-clip__play")!;
    expect(play.textContent).toContain("Tap to play");
    expect(play.getAttribute("aria-label")).toContain(props.label);
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    await act(async () => play.click());
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(host.querySelector(".lp-clip__play")).toBeNull();
    await act(async () => root.unmount());
  });
});
