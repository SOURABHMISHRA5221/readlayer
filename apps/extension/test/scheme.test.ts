import { describe, expect, it, vi } from "vitest";

vi.stubGlobal("chrome", { runtime: { sendMessage: vi.fn() } });
const { pageScheme } = await import("../src/content");

function page(html: string): Element {
  document.body.innerHTML = html;
  return document.getElementById("a")!;
}

describe("pageScheme (notes match the page, not the OS)", () => {
  it("a page with no background is light", () => {
    expect(pageScheme(page('<article id="a"><p>x</p></article>'))).toBe("light");
  });
  it("takes the first opaque background up the tree", () => {
    expect(pageScheme(page('<div style="background: rgb(18, 18, 18)"><article id="a" style="background: rgba(0,0,0,0)"></article></div>'))).toBe("dark");
    expect(pageScheme(page('<div style="background: #121212"><article id="a" style="background: #fff"></article></div>'))).toBe("light");
  });
});
