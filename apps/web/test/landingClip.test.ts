// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClipView } from "../src/landing/Clip";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// One IntersectionObserver stand-in: every observed element counts as on screen.
class OnScreen {
  constructor(private cb: IntersectionObserverCallback) {}
  observe(el: Element) {
    this.cb([{ isIntersecting: true, target: el } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
  disconnect() {}
}

const props = { name: "clip-note", label: "tapping a highlighted term opens its note", width: 720, height: 482 };

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
    expect(video.querySelectorAll("source")).toHaveLength(2);
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
});
