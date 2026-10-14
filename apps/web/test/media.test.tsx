// @vitest-environment jsdom
import { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/lib/auth", () => ({
  idToken: async () => "token",
  signOutUser: async () => undefined,
  useIsDemo: () => false,
  useSession: () => ({ status: "signed_out" }),
}));

import MediaReader, { TranscriptBody } from "../src/components/reader/MediaReader";
import { opensHere, type ContentDetail, type MediaInfo } from "../src/lib/api";
import {
  clock,
  currentTimeOf,
  embedUrl,
  LISTENING,
  paragraphAt,
  seekTo,
  shouldFollow,
  YOUTUBE_ORIGIN,
} from "../src/lib/media";
import { ReadAnyLink } from "../src/components/ReadAnyLink";
import { ReaderPage } from "../src/pages/ReaderPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MEDIA: MediaInfo = { kind: "video", video_id: "d6fUwCBvVc0", audio_url: null, duration_s: 960 };
const EPISODE: MediaInfo = { kind: "podcast", video_id: null, audio_url: "https://traffic.example.fm/ep/rates.mp3", duration_s: 1320 };
const APPLE_URL = "https://podcasts.apple.com/us/podcast/rates/id1234567890?i=1000700000000";
const PARAGRAPHS: ContentDetail["paragraphs"] = [
  { id: "p0", text: "Interest rates set the price of money.", start_s: 2 },
  { id: "p1", text: "The yield curve shows rates by maturity.", start_s: 95 },
  { id: "p2", text: "When it inverts, markets worry.", start_s: 760 },
];

describe("lib/media", () => {
  it("finds the paragraph being spoken", () => {
    const starts = [2, 95, 760];
    expect(paragraphAt(starts, 0)).toBe(-1);
    expect(paragraphAt(starts, 2)).toBe(0);
    expect(paragraphAt(starts, 94.9)).toBe(0);
    expect(paragraphAt(starts, 95)).toBe(1);
    expect(paragraphAt(starts, 5000)).toBe(2);
    expect(paragraphAt([], 10)).toBe(-1);
  });

  it("writes times as a clock", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(760)).toBe("12:40");
    expect(clock(3725)).toBe("1:02:05");
  });

  it("builds the youtube.com embed with the JS API and a start time", () => {
    const u = new URL(embedUrl("abc_DEF-123", "https://gloss.example", 95.7));
    expect(u.origin).toBe("https://www.youtube.com"); // decision 55: the no-cookie player is challenged
    expect(u.pathname).toBe("/embed/abc_DEF-123");
    expect(u.searchParams.get("enablejsapi")).toBe("1");
    expect(u.searchParams.get("origin")).toBe("https://gloss.example");
    expect(u.searchParams.get("start")).toBe("95");
    expect(u.searchParams.get("rel")).toBe("0");
  });

  it("encodes player commands", () => {
    expect(JSON.parse(LISTENING)).toEqual({ event: "listening", id: 1, channel: "widget" });
    expect(JSON.parse(seekTo(760))).toEqual({ event: "command", func: "seekTo", args: [760, true], id: 1, channel: "widget" });
  });

  it("reads the time only from our own player on the YouTube origin", () => {
    const player = {};
    const info = JSON.stringify({ event: "infoDelivery", info: { currentTime: 96.2 } });
    expect(currentTimeOf({ origin: YOUTUBE_ORIGIN, source: player as Window, data: info }, player)).toBe(96.2);
    expect(YOUTUBE_ORIGIN).toBe("https://www.youtube.com");
    for (const origin of ["https://www.youtube-nocookie.com", "https://youtube.com", "https://m.youtube.com", "https://www.youtube.com.evil.example"]) {
      expect(currentTimeOf({ origin, source: player as Window, data: info }, player)).toBeNull();
    }
    expect(currentTimeOf({ origin: YOUTUBE_ORIGIN, source: {} as Window, data: info }, player)).toBeNull();
    expect(currentTimeOf({ origin: YOUTUBE_ORIGIN, source: player as Window, data: "not json" }, player)).toBeNull();
    const noTime = JSON.stringify({ event: "infoDelivery", info: { volume: 50 } });
    expect(currentTimeOf({ origin: YOUTUBE_ORIGIN, source: player as Window, data: noTime }, player)).toBeNull();
    expect(currentTimeOf({ origin: YOUTUBE_ORIGIN, source: null, data: info }, null)).toBeNull();
  });

  it("pauses Follow for five seconds after a manual scroll", () => {
    expect(shouldFollow(true, 0, 10_000)).toBe(true);
    expect(shouldFollow(true, 8000, 10_000)).toBe(false);
    expect(shouldFollow(false, 0, 10_000)).toBe(false);
  });

  it("opens items here as the server says; older APIs, articles only", () => {
    expect(opensHere({ format: "video", open_here: true })).toBe(true);
    expect(opensHere({ format: "video" })).toBe(false);
    expect(opensHere({ format: "article" })).toBe(true);
    expect(opensHere({ format: "article", open_here: false })).toBe(false);
  });
});

let root: Root;
let host: HTMLDivElement;

async function render(node: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(node));
}

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("MediaReader", () => {
  async function mountReader() {
    const article = createRef<HTMLElement>();
    await render(
      <>
        <MediaReader contentId="abc123" transcribing={false} onTranscribed={() => undefined} media={MEDIA} title="Rates, explained" url="https://www.youtube.com/watch?v=d6fUwCBvVc0" paragraphs={PARAGRAPHS} article={article} />
        <TranscriptBody ref={article} paragraphs={PARAGRAPHS} onMount={() => undefined} />
      </>,
    );
    return article;
  }
  const iframe = () => host.querySelector("iframe");
  const timeButton = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="Play from ${label}"]`)!;

  it("loads no player until play is pressed, then the youtube.com embed", async () => {
    await mountReader();
    expect(iframe()).toBeNull();
    const thumb = host.querySelector<HTMLImageElement>(".mplayer__facade img")!;
    expect(thumb.getAttribute("referrerpolicy")).toBe("no-referrer");
    await act(async () => host.querySelector<HTMLButtonElement>(".mplayer__facade")!.click());
    const src = new URL(iframe()!.src);
    expect(src.origin).toBe("https://www.youtube.com");
    expect(iframe()!.getAttribute("referrerpolicy")).toBe("strict-origin");
    expect(src.searchParams.get("start")).toBe("0");
  });

  it("puts a labelled time button in each paragraph, outside the text", async () => {
    const article = await mountReader();
    const buttons = [...article.current!.querySelectorAll("button")];
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Play from 0:02", "Play from 1:35", "Play from 12:40"]);
    expect(buttons.every((b) => b.getAttribute("data-rl-ui") === "host")).toBe(true);
  });

  it("a time button starts the player there, then seeks it", async () => {
    const article = await mountReader();
    await act(async () => timeButton("12:40").click());
    expect(new URL(iframe()!.src).searchParams.get("start")).toBe("760");
    expect(article.current!.querySelector("[data-rl-now]")?.getAttribute("data-rl-paragraph")).toBe("p2");

    const post = vi.spyOn(iframe()!.contentWindow!, "postMessage").mockImplementation(() => undefined);
    await act(async () => timeButton("1:35").click());
    expect(post).toHaveBeenCalledWith(seekTo(95), YOUTUBE_ORIGIN);
    expect(article.current!.querySelector("[data-rl-now]")?.getAttribute("data-rl-paragraph")).toBe("p1");
  });

  it("marks the spoken paragraph from the player's time and ignores other windows", async () => {
    const article = await mountReader();
    await act(async () => host.querySelector<HTMLButtonElement>(".mplayer__facade")!.click());
    const win = iframe()!.contentWindow!;
    const data = (t: number) => JSON.stringify({ event: "infoDelivery", info: { currentTime: t } });
    const now = () => article.current!.querySelector("[data-rl-now]")?.getAttribute("data-rl-paragraph");

    await act(async () => window.dispatchEvent(new MessageEvent("message", { origin: YOUTUBE_ORIGIN, source: win, data: data(100) })));
    expect(now()).toBe("p1");
    await act(async () => window.dispatchEvent(new MessageEvent("message", { origin: "https://evil.example", source: win, data: data(800) })));
    expect(now()).toBe("p1");
    await act(async () => window.dispatchEvent(new MessageEvent("message", { origin: YOUTUBE_ORIGIN, source: window, data: data(800) })));
    expect(now()).toBe("p1");
  });

  it("Follow is a toggle", async () => {
    await mountReader();
    const follow = host.querySelector<HTMLButtonElement>(".mplayer__follow")!;
    expect(follow.getAttribute("aria-pressed")).toBe("true");
    await act(async () => follow.click());
    expect(follow.getAttribute("aria-pressed")).toBe("false");
  });
});

describe("AudioPlayer", () => {
  let play: ReturnType<typeof vi.fn>;
  async function mountEpisode() {
    play = vi.fn(async () => undefined);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(play as unknown as () => Promise<void>);
    const article = createRef<HTMLElement>();
    await render(
      <>
        <MediaReader contentId="ep1" transcribing={false} onTranscribed={() => undefined} media={EPISODE} title="Rates, explained" url={APPLE_URL} paragraphs={PARAGRAPHS} article={article} />
        <TranscriptBody ref={article} paragraphs={PARAGRAPHS} onMount={() => undefined} />
      </>,
    );
    return article;
  }
  const audio = () => host.querySelector("audio")!;
  const now = (article: React.RefObject<HTMLElement | null>) => article.current!.querySelector("[data-rl-now]")?.getAttribute("data-rl-paragraph");

  it("streams from the publisher only on play: no preload, no YouTube, no referrer attribute", async () => {
    await mountEpisode();
    expect(audio().getAttribute("src")).toBe(EPISODE.audio_url);
    expect(audio().getAttribute("preload")).toBe("none");
    expect(audio().hasAttribute("controls")).toBe(true);
    expect(audio().hasAttribute("referrerpolicy")).toBe(false);
    expect(host.querySelector("iframe, .mplayer__facade")).toBeNull();
    expect(host.querySelector<HTMLAnchorElement>(".mplayer__original")?.href).toBe(APPLE_URL);
    expect(play).not.toHaveBeenCalled();
  });

  it("a time button seeks the audio and plays it", async () => {
    const article = await mountEpisode();
    await act(async () => host.querySelector<HTMLButtonElement>('button[aria-label="Play from 12:40"]')!.click());
    expect(audio().currentTime).toBe(760);
    expect(play).toHaveBeenCalledTimes(1);
    expect(now(article)).toBe("p2");
  });

  it("marks the spoken paragraph as the audio plays", async () => {
    const article = await mountEpisode();
    const tick = async (t: number) => {
      audio().currentTime = t;
      await act(async () => audio().dispatchEvent(new Event("timeupdate")));
    };
    await tick(1);
    expect(now(article)).toBeUndefined();
    await tick(100);
    expect(now(article)).toBe("p1");
    await tick(761);
    expect(now(article)).toBe("p2");
  });

  it("audio that won't play says so and offers the original; the transcript stays", async () => {
    const article = await mountEpisode();
    await act(async () => audio().dispatchEvent(new Event("error")));
    expect(host.querySelector("audio")).toBeNull();
    const stop = host.querySelector(".reader__notice--stop")!;
    expect(stop.textContent).toContain("This episode's audio couldn't be played here.");
    expect(stop.querySelector("a")?.getAttribute("href")).toBe(APPLE_URL);
    expect(article.current!.querySelectorAll("p")).toHaveLength(3);
  });
});

describe("Read any link copy", () => {
  afterEach(() => vi.unstubAllEnvs());
  const placeholder = () => host.querySelector("input")!.getAttribute("placeholder");

  it("names YouTube when the video switch is on (the default)", async () => {
    await render(<ReadAnyLink persona={null} />);
    expect(placeholder()).toBe("Paste an article, YouTube or podcast link");
    expect(host.textContent).toContain("Videos and podcasts get a transcript.");
  });

  it("leaves YouTube out when the build has it off", async () => {
    vi.stubEnv("VITE_MEDIA_VIDEO", "false");
    await render(<ReadAnyLink persona={null} />);
    expect(placeholder()).toBe("Paste an article or podcast link");
    expect(host.textContent).toContain("Podcasts get a transcript.");
    expect(host.textContent).not.toContain("Videos");
  });
});

describe("ReaderPage with a recording", () => {
  const ID = "abc123";
  const base = {
    id: ID,
    title: "Rates, explained",
    site: "Money Channel",
    url: "https://www.youtube.com/watch?v=d6fUwCBvVc0",
    word_count: 1800,
    description: null,
    author: null,
    published: null,
    image: null,
    domain: "finance",
    media: MEDIA,
    refusal: null,
  };
  const transcribing = { ...base, paragraphs: [], status: "transcribing" };
  const analysing = { ...base, paragraphs: PARAGRAPHS, status: "analysing" };
  const NOTES = { content_id: ID, persona: null, density: "balanced", count: 0, annotations: [] };

  let calls: string[];
  type Reply = { status: number; body: unknown };
  const json = ({ status, body }: Reply) => new Response(JSON.stringify(body), { status });

  function stub(content: Reply[], transcribe: Reply[]) {
    calls = [];
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      const u = new URL(url, "http://localhost");
      const call = `${init?.method ?? "GET"} ${u.pathname}`;
      calls.push(call);
      if (call === `GET /v1/content/${ID}`) return json(content.length > 1 ? content.shift()! : content[0]!);
      if (call === `POST /v1/content/${ID}/transcribe`) return json(transcribe.length > 1 ? transcribe.shift()! : transcribe[0]!);
      if (call === `POST /v1/content/${ID}/analyse`) return json({ status: 200, body: { content_id: ID, status: "ready" } });
      if (call === `GET /v1/content/${ID}/annotations`) return json({ status: 200, body: NOTES });
      if (u.pathname.startsWith("/v1/me/saved")) return json({ status: 200, body: [] });
      return json({ status: 200, body: { items: [], pending: false } });
    });
  }

  async function open() {
    await render(<ReaderPage id={ID} url={new URL(`http://localhost/read/${ID}`)} />);
  }
  const settle = (until: () => boolean) =>
    vi.waitFor(async () => {
      await act(async () => new Promise((r) => setTimeout(r, 5)));
      expect(until()).toBe(true);
    }, { timeout: 3000 });
  const transcribeCalls = () => calls.filter((c) => c.endsWith("/transcribe")).length;

  beforeEach(() => {
    window.scrollTo = () => undefined;
  });

  it("transcribes (retrying a timeout once), shows the transcript, then the notes", async () => {
    stub(
      [{ status: 200, body: transcribing }, { status: 200, body: analysing }],
      [{ status: 504, body: { error: "transcribe_timeout", message: "Transcribing took too long. Try again." } }, { status: 200, body: { content_id: ID, status: "analysing" } }],
    );
    await open();
    expect(host.querySelector(".article-head__kicker")?.textContent).toBe("Video · 16 min · Money Channel");
    expect(host.querySelector(".mplayer__facade")).not.toBeNull(); // the player works while transcribing
    await settle(() => calls.includes(`GET /v1/content/${ID}/annotations`));
    expect(transcribeCalls()).toBe(2);
    expect(host.querySelectorAll(".prose--transcript p")).toHaveLength(3);
    expect(host.querySelector(".prose--transcript")?.textContent).toContain("When it inverts, markets worry.");
    expect(document.querySelector(".rl-card__says .rl-card__section-label")?.textContent).toBe("What the speaker is saying");
    expect(host.querySelector('[role="alert"]')).toBeNull();
  });

  it("a podcast: the kicker, the audio bar while transcribing, then the transcript", async () => {
    const episode = { ...base, site: "Planet Money", url: APPLE_URL, media: EPISODE };
    stub(
      [{ status: 200, body: { ...episode, paragraphs: [], status: "transcribing" } }, { status: 200, body: { ...episode, paragraphs: PARAGRAPHS, status: "analysing" } }],
      [{ status: 200, body: { content_id: ID, status: "analysing" } }],
    );
    await open();
    expect(host.querySelector(".article-head__kicker")?.textContent).toBe("Podcast · 22 min · Planet Money");
    expect(host.querySelector("audio")?.getAttribute("src")).toBe(EPISODE.audio_url); // usable while transcribing
    await settle(() => calls.includes(`GET /v1/content/${ID}/annotations`));
    expect(transcribeCalls()).toBe(1);
    expect(host.querySelectorAll(".prose--transcript p")).toHaveLength(3);
    expect(host.querySelector(".mplayer__original")?.textContent).toContain("Open in Apple Podcasts");
  });

  it("a second timeout stops with Try again and Open original", async () => {
    const timeout = { status: 504, body: { error: "transcribe_timeout", message: "Transcribing took too long. Try again." } };
    stub([{ status: 200, body: transcribing }], [timeout]);
    await open();
    await settle(() => !!host.querySelector(".reader__notice--stop"));
    expect(transcribeCalls()).toBe(2);
    const stop = host.querySelector(".reader__notice--stop")!;
    expect(stop.textContent).toContain("Transcribing took too long. Try again.");
    expect([...stop.querySelectorAll("button, a")].map((b) => b.textContent?.replace(" (opens in a new tab)", ""))).toEqual(["Try again", "Open original"]);
  });

  it("a refusal shows the API's message and Open original, and stops calling", async () => {
    stub([{ status: 200, body: transcribing }], [{ status: 422, body: { error: "not_english", message: "Gloss reads English recordings only for now." } }]);
    await open();
    await settle(() => !!host.querySelector(".reader__notice--stop"));
    expect(host.querySelector(".reader__notice--stop")?.textContent).toContain("Gloss reads English recordings only for now.");
    expect(host.querySelector(".reader__notice--stop button")).toBeNull();
    await act(async () => new Promise((r) => setTimeout(r, 30)));
    expect(transcribeCalls()).toBe(1);
  });

  it("a stored refusal or failure needs no call", async () => {
    stub([{ status: 200, body: { ...transcribing, status: "refused", refusal: { code: "too_long", message: "This one is too long to transcribe." } } }], []);
    await open();
    await settle(() => !!host.querySelector(".reader__notice--stop"));
    expect(host.querySelector(".reader__notice--stop")?.textContent).toContain("This one is too long to transcribe.");
    expect(transcribeCalls()).toBe(0);
  });
});
