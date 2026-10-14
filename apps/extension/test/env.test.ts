import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Decision 62: the production build's web base is one of the origins it accepts, and both
// Hosting sites (new and old) can connect.
const env = Object.fromEntries(
  readFileSync(resolve(__dirname, "../.env.production"), "utf8")
    .split("\n")
    .filter((line) => /^[A-Z_]+=/.test(line))
    .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)]),
);

describe(".env.production", () => {
  const origins = env.VITE_WEB_ORIGINS!.split(",");
  it("the web base is an accepted origin", () => {
    expect(origins).toContain(env.VITE_WEB_BASE);
  });
  it("accepts both Hosting sites on both domains", () => {
    for (const site of ["glossreader", "readlayer-sourabh-26"]) {
      for (const domain of ["web.app", "firebaseapp.com"]) expect(origins).toContain(`https://${site}.${domain}`);
    }
  });
});
