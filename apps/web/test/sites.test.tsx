import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { authDomainFor, GLOSS_HOST } from "../src/lib/sites";
import { OlderExtensionHint } from "../src/pages/ConnectPage";

const BUILT = "readlayer-sourabh-26.firebaseapp.com";

describe("authDomainFor (decision 62, R11)", () => {
  it("signs in through the page's own host on glossreader.web.app, so Google names it", () => {
    expect(GLOSS_HOST).toBe("glossreader.web.app");
    expect(authDomainFor("glossreader.web.app", BUILT)).toBe("glossreader.web.app");
  });
  it.each(["readlayer-sourabh-26.web.app", "glossreader.firebaseapp.com", "localhost"])(
    "keeps the built authDomain on %s",
    (host) => {
      expect(authDomainFor(host, BUILT)).toBe(BUILT);
    },
  );
});

describe("Connect page hint for Gloss 0.8.1 (decision 62)", () => {
  it("on the new address, says 0.8.1 connects from the old one and links 0.8.2", () => {
    const html = renderToStaticMarkup(<OlderExtensionHint hostname="glossreader.web.app" />);
    expect(html).toContain("readlayer-sourabh-26.web.app");
    expect(html).toContain("/releases/tag/extension-v0.8.2");
  });
  it("on the old address, says nothing (0.8.1 connects there)", () => {
    for (const host of ["readlayer-sourabh-26.web.app", "readlayer-sourabh-26.firebaseapp.com"]) {
      expect(renderToStaticMarkup(<OlderExtensionHint hostname={host} />)).toBe("");
    }
  });
});
