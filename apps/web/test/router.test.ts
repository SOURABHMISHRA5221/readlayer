import { describe, expect, it } from "vitest";

import { matchRoute, onboardingRedirect } from "../src/lib/router";

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
