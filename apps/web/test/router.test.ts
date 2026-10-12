// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  matchRoute,
  onboardingRedirect,
  rememberReturn,
  returnsAfterOnboarding,
  takeReturn,
} from "../src/lib/router";

describe("onboarding gate", () => {
  it("sends a reader who hasn't finished onboarding to /welcome from anywhere else", () => {
    expect(onboardingRedirect(false, "library")).toBe("/welcome");
    expect(onboardingRedirect(false, "profile")).toBe("/welcome");
    expect(onboardingRedirect(false, "welcome")).toBeNull();
  });
  it("leaves finished readers, demo readers and still-loading status alone", () => {
    expect(onboardingRedirect(true, "library")).toBeNull();
    expect(onboardingRedirect(null, "reader")).toBeNull();
  });
  it("knows the new routes", () => {
    expect(matchRoute("/welcome")).toEqual({ name: "welcome" });
    expect(matchRoute("/profile")).toEqual({ name: "profile" });
  });
});

describe("the extension's Connect page (M8 §D)", () => {
  it("is a route under the onboarding gate", () => {
    expect(matchRoute("/connect")).toEqual({ name: "connect" });
    expect(onboardingRedirect(false, "connect")).toBe("/welcome");
  });
  it("is the only route the gate brings a reader back to after onboarding", () => {
    expect(returnsAfterOnboarding("connect")).toBe(true);
    for (const route of ["library", "reader", "profile", "feed"] as const) {
      expect(returnsAfterOnboarding(route)).toBe(false);
    }
  });
  it("survives the round trip through /welcome", () => {
    rememberReturn("/connect");
    expect(takeReturn()).toBe("/connect");
    expect(takeReturn()).toBeNull(); // once
  });
});
