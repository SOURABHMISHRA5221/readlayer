// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import PrivacyPage from "../src/pages/PrivacyPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("privacy page, videos (decision 55)", () => {
  it("says what the youtube.com player shares, and no longer claims the no-cookie domain", async () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => root.render(<PrivacyPage />));
    const videos = host.querySelector('section[aria-labelledby="pv-videos"]')!.textContent!;
    expect(videos).not.toMatch(/no-cookie/i);
    expect(videos).toMatch(/thumbnail/);
    expect(videos).toMatch(/only when you press play/);
    expect(videos).toMatch(/may set cookies/);
    expect(videos).toMatch(/signed in to YouTube/);
    expect(videos).toMatch(/Gloss's site/);
    await act(async () => root.unmount());
    host.remove();
  });
});
