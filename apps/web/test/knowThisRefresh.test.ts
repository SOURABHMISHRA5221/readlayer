// @vitest-environment jsdom
import { createAnnotator, type CardAnnotation, type PromptAnnotation } from "@readlayer/annotator";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({ idToken: async () => "token" }));

import { answerAndRefresh, REFRESH_AFTER_ANSWER_MS, withoutPrompts } from "../src/lib/answers";
import { api } from "../src/lib/api";

// Decision 46d: a saved "Know this?" answer refetches the notes, so marks change in place.

const prompt: PromptAnnotation = {
  id: "ask-hedging", kind: "prompt", anchor: { exact: "hedging", prefix: "", suffix: "" }, paragraph_id: "p0",
  concept_id: "c_hedging", label: "Hedging",
} as PromptAnnotation; // prettier-ignore

const hedging: CardAnnotation = {
  id: "d1", kind: "span", anchor: { exact: "hedging", prefix: "", suffix: "" }, paragraph_id: "p0", score: 0.7,
  concept_id: "c_hedging", label: "Hedging", definition: "Hedging defined.", domain: "finance", prerequisites: [],
}; // prettier-ignore

/** The article's own text: inserted annotator UI (data-rl-ui) is never part of it. */
function articleText(root: HTMLElement): string | null {
  const copy = root.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("[data-rl-ui]").forEach((el) => el.remove());
  return copy.textContent;
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("Know this? answers", () => {
  it("refreshes the notes after the answer is saved, once the chip has said Noted", async () => {
    vi.useFakeTimers();
    const order: string[] = [];
    await answerAndRefresh({
      save: async () => void order.push("save"),
      refresh: async () => void order.push("refresh"),
    });
    expect(order).toEqual(["save"]);
    await vi.advanceTimersByTimeAsync(REFRESH_AFTER_ANSWER_MS);
    expect(order).toEqual(["save", "refresh"]);
  });

  it("a failed save refreshes nothing and reaches the chip", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn(async () => undefined);
    await expect(answerAndRefresh({ save: async () => Promise.reject(new Error("503")), refresh })).rejects.toThrow("503");
    await vi.advanceTimersByTimeAsync(REFRESH_AFTER_ANSWER_MS * 2);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("skips the refresh once the reader has moved to another article or persona", async () => {
    vi.useFakeTimers();
    const refresh = vi.fn(async () => undefined);
    let current = true;
    await answerAndRefresh({ save: async () => undefined, refresh, isCurrent: () => current });
    current = false; // e.g. switched persona within the wait
    await vi.advanceTimersByTimeAsync(REFRESH_AFTER_ANSWER_MS);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("asks the API for a refresh, not a new page view", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ content_id: "a", persona: null, density: "balanced", count: 0, annotations: [] }), { status: 200 })));
    await api.annotations("a", null, "balanced", false, undefined, true);
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("refresh=1");
    vi.unstubAllGlobals();
  });

  it("a failed refresh keeps the current marks and doesn't throw", async () => {
    vi.useFakeTimers();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await answerAndRefresh({ save: async () => undefined, refresh: async () => Promise.reject(new Error("net")) });
    await vi.advanceTimersByTimeAsync(REFRESH_AFTER_ANSWER_MS);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("“Not really” turns the term into a highlight in place; “Yes” removes its mark", async () => {
    document.body.innerHTML = `<article id="root"><p data-rl-paragraph="p0">Exporters keep hedging their receivables and buying forwards.</p></article>`;
    const root = document.getElementById("root")!;
    const text = root.textContent;
    const forwards = { ...prompt, id: "ask-forwards", anchor: { exact: "forwards", prefix: "", suffix: "" }, concept_id: "c_fwd" };
    let respond: (known: boolean) => (CardAnnotation | PromptAnnotation)[] = () => [];
    const annotator = createAnnotator(root, {
      leaveMs: 0,
      staggerMs: 0,
      onAnswer: (_p, known) =>
        answerAndRefresh({
          save: async () => undefined,
          // The refetched notes go through the same filter as ReaderPage's refresh.
          refresh: async () => {
            const all = respond(known);
            await annotator.update([...all.filter((a) => a.kind === "span"), ...withoutPrompts(all)]);
          },
          waitMs: 0,
        }),
    });
    const chip = () => root.querySelector<HTMLElement>(".rl-ask");
    const press = (label: string) => [...root.querySelectorAll<HTMLButtonElement>(".rl-ask button")].find((b) => b.textContent === label)!.click();

    // "Not really": the API now returns the term as a span (and, wrongly, another prompt).
    respond = () => [hedging, forwards];
    await annotator.update([prompt]);
    press("Not really");
    await vi.waitFor(() => expect(root.querySelector('[data-rl-id="d1"]')).not.toBeNull());
    expect(root.querySelectorAll(".rl-ask")).toHaveLength(1); // no second chip mid-read
    expect(chip()?.dataset.state).toBe("done");
    expect(chip()?.textContent).toContain("Noted, thanks.");
    expect(articleText(root)).toBe(text); // the article's words never change

    annotator.destroy();

    // "Yes": the refetch (API: known → neither a span nor a prompt) leaves no mark on the term.
    document.body.innerHTML = `<article id="root2"><p data-rl-paragraph="p0">Exporters keep hedging their receivables.</p></article>`;
    const root2 = document.getElementById("root2")!;
    const second = createAnnotator(root2, {
      leaveMs: 0,
      staggerMs: 0,
      onAnswer: () => answerAndRefresh({ save: async () => undefined, refresh: () => second.update([]).then(() => undefined), waitMs: 0 }),
    });
    await second.update([prompt]);
    expect(root2.querySelector(".rl-mark--ask")).not.toBeNull();
    [...root2.querySelectorAll<HTMLButtonElement>(".rl-ask button")].find((b) => b.textContent === "Yes")!.click();
    await vi.waitFor(() => expect(root2.querySelector(".rl-mark--ask")).toBeNull());
    expect(root2.querySelectorAll(".rl-mark")).toHaveLength(0);
    expect(root2.querySelector<HTMLElement>(".rl-ask")?.dataset.state).toBe("done");
    second.destroy();
  });
});
