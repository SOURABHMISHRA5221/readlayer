import {
  createAnnotator,
  renderPreread,
  type Annotator,
  type AnnotatorEvent,
  type AnyAnnotation,
  type CardAnnotation,
  type Explanation,
  type PrereadAnnotation,
} from "@readlayer/annotator";

import { extractArticle, type Extracted } from "./extract";
import type { ApiOp, ApiReply, ReaderEvent } from "./messages";
import { redact, redactUrl } from "./redact";
import { refusal, type Refusal } from "./refuse";
import { tagParagraphs, type ServerParagraph } from "./tag";
import { finalToast, type GrowStatus, growUntilDone, shouldGrow } from "./grow";
import { showToast } from "./toast";

/**
 * Content script (M8 §C3), injected only when the reader clicks "Read this page". `prepare` runs
 * first and touches nothing: refusals, the already-mounted check, extraction. Only for an
 * accepted page does the worker insert our CSS and call `start`, which submits the redacted text
 * through the worker (it holds the token), waits for the analysis, tags the live paragraphs and
 * mounts the shared annotator. The page's text is never changed.
 */

export type Prepared = { mounted: true } | { refused: Refusal } | { noArticle: true } | { ready: true };

const MOUNTED_ATTR = "data-rl-mounted";
const SCHEME_ATTR = "data-rl-scheme";
const ANALYSE_LIMIT_MS = 180_000;
const RETRY_MS = 2_000;
const FLUSH_MS = 5_000;
const REFRESH_AFTER_ANSWER_MS = 1_200;
const PREFETCH_TOP = 3;

let extracted: Extracted | null = null;

function api<T>(call: ApiOp): Promise<ApiReply<T>> {
  return chrome.runtime.sendMessage({ type: "api", call }) as Promise<ApiReply<T>>;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function prepare(): Prepared {
  if (document.documentElement.hasAttribute(MOUNTED_ATTR)) return { mounted: true };
  const refused = refusal(document, location.href);
  if (refused) return { refused };
  extracted = extractArticle(document);
  return extracted ? { ready: true } : { noArticle: true };
}

interface Submitted {
  content_id: string;
  status?: "ready" | "analysing";
}

async function analysed(id: string): Promise<boolean> {
  const until = Date.now() + ANALYSE_LIMIT_MS;
  while (Date.now() < until) {
    const res = await api<{ status: "ready" | "analysing" }>({ op: "analyse", id });
    if (!res.ok) {
      showToast(res.message);
      return false;
    }
    if (res.status === 200) return true;
    await sleep(RETRY_MS); // 202: another request is analysing it
  }
  showToast("Analysing this page is taking too long. Try again in a minute.");
  return false;
}

async function start({ webBase }: { webBase: string }): Promise<void> {
  if (!extracted || document.documentElement.hasAttribute(MOUNTED_ATTR)) return;
  document.documentElement.setAttribute(MOUNTED_ATTR, "");
  showToast("Reading this page…", { busy: true });
  const page = extracted;
  const submitted = await api<Submitted>({
    op: "submit",
    url: redactUrl(location.href),
    title: redact(page.title),
    paragraphs: page.paragraphs.map(redact),
  });
  if (!submitted.ok) {
    document.documentElement.removeAttribute(MOUNTED_ATTR);
    showToast(submitted.message);
    return;
  }
  const id = submitted.data.content_id;
  const analysing = submitted.data.status === "analysing";
  if (analysing && !(await analysed(id))) {
    document.documentElement.removeAttribute(MOUNTED_ATTR);
    return;
  }
  const detail = await api<{ paragraphs: ServerParagraph[]; grow_pending?: boolean }>({ op: "detail", id });
  const tagged = detail.ok ? tagParagraphs(document, detail.data.paragraphs) : null;
  if (!tagged) {
    document.documentElement.removeAttribute(MOUNTED_ATTR); // a later click may try again
    showToast("Gloss couldn't place notes on this page.");
    return;
  }
  let grown: GrowStatus | null = null;
  if (detail.ok && shouldGrow(detail.data)) {
    showToast("Adding this page's ideas to your map…", { busy: true });
    grown = await growUntilDone(id, (op) => api(op));
  }
  const notes = await loadNotes(id);
  if (!notes) {
    document.documentElement.removeAttribute(MOUNTED_ATTR);
    showToast("Notes couldn't load. Try again in a minute.");
    return;
  }
  document.documentElement.setAttribute(SCHEME_ATTR, pageScheme(tagged.root));
  const overlay = mountOverlay(id, tagged.root, webBase);
  const { resolved } = await overlay.show(notes);
  const preread = notes.find((a): a is PrereadAnnotation => a.kind === "preread");
  if (preread) overlay.preread(preread, tagged.elements.values().next().value!);
  showToast(finalToast(resolved, grown), { hideAfterMs: grown === "capped" && !resolved ? 8_000 : 4_000 });
}

/** Light or dark, from the article's own background (the first opaque one up the tree). */
export function pageScheme(from: Element): "light" | "dark" {
  for (let el: Element | null = from; el; el = el.parentElement) {
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(getComputedStyle(el).backgroundColor);
    if (!m || (m[4] !== undefined && Number(m[4]) < 0.5)) continue;
    const [r, g, b] = [m[1], m[2], m[3]].map((v) => Number(v) / 255) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45 ? "dark" : "light";
  }
  return "light"; // browsers paint a transparent page white
}

async function loadNotes(id: string, refresh = false): Promise<AnyAnnotation[] | null> {
  const res = await api<{ annotations: AnyAnnotation[] }>({ op: "annotations", id, refresh });
  return res.ok ? res.data.annotations : null;
}

interface Overlay {
  show(notes: AnyAnnotation[]): Promise<{ resolved: number }>;
  preread(item: PrereadAnnotation, before: HTMLElement): void;
}

function mountOverlay(contentId: string, root: HTMLElement, webBase: string): Overlay {
  const explanations = new Map<string, Promise<Explanation>>();
  const loadExplanation = (a: CardAnnotation): Promise<Explanation> => {
    const hit = explanations.get(a.id);
    if (hit) return hit;
    const target = a.kind === "paragraph" ? { paragraph_id: a.paragraph_id } : { demand_id: a.id };
    const pending = api<Explanation>({ op: "explain", id: contentId, target }).then((r) => {
      if (!r.ok) throw new Error(r.error);
      const e = r.data;
      return {
        id: e.id, kind: e.kind, background: e.background, author_says: e.author_says,
        analogy_domain: e.analogy_domain, band: e.band, can_simpler: false, can_deeper: false,
      };  // prettier-ignore
    });
    explanations.set(a.id, pending);
    pending.catch(() => explanations.delete(a.id));
    return pending;
  };

  const events = batcher(contentId);
  let annotator: Annotator | null = null;
  const onEvent = (event: AnnotatorEvent) => {
    if (event.type === "report_wrong") {
      if (event.explanation_id && event.annotation_id) {
        explanations.delete(event.annotation_id);
        void api({ op: "report", explanation_id: event.explanation_id, content_id: contentId,
          concept_id: event.concept_id });  // prettier-ignore
      }
      return;
    }
    events.add(event);
  };

  annotator = createAnnotator(root, {
    styles: "external",
    actions: "full",
    onEvent,
    loadExplanation,
    // "Know this?": saved to the reader's graph, then the notes are refetched in place (46d).
    onAnswer: async (prompt, known) => {
      const saved = await api({ op: "answer", concept_id: prompt.concept_id, known });
      if (!saved.ok) throw new Error(saved.error);
      setTimeout(() => {
        void loadNotes(contentId, true).then((notes) => {
          if (notes && annotator) void annotator.update(notes.filter((n) => n.kind !== "prompt"), { reader: "me" });
        });
      }, REFRESH_AFTER_ANSWER_MS);
    },
  });
  events.beforeFlush(() => annotator?.flush());

  return {
    async show(notes) {
      const result = await annotator!.update(notes, { reader: "me" });
      const spans = notes.filter((n): n is CardAnnotation => n.kind === "span");
      [...spans].sort((a, b) => b.score - a.score).slice(0, PREFETCH_TOP)
        .forEach((a) => void loadExplanation(a).catch(() => undefined));  // prettier-ignore
      return { resolved: result.resolved.length };
    },
    preread(item, before) {
      const holder = document.createElement("div");
      holder.className = "rl-ext-preread";
      holder.setAttribute("data-rl-ui", "");
      before.before(holder);
      renderPreread(holder, item, {
        styles: "external",
        href: (step) => (step.content_id ? `${webBase}/read/${encodeURIComponent(step.content_id)}` : "#"),
        onOpen: (step, ev) => {
          if (!step.content_id) return;
          ev.preventDefault();
          window.open(`${webBase}/read/${encodeURIComponent(step.content_id)}`, "_blank", "noopener");
        },
      });
    },
  };
}

/** Reading events batched every 5 s and on page hide (DESIGN §9), one retry per failed batch. */
function batcher(contentId: string) {
  let queue: { event: ReaderEvent; retried: boolean }[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  const hooks: (() => void)[] = [];
  const flush = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    const batch = queue;
    queue = [];
    if (!batch.length) return;
    void api({ op: "events", events: batch.map((b) => b.event) }).then((res) => {
      if (res.ok) return;
      const again = batch.filter((b) => !b.retried).map((b) => ({ ...b, retried: true }));
      if (again.length) {
        queue = [...queue, ...again];
        timer ??= setTimeout(flush, FLUSH_MS);
      }
    });
  };
  const onHide = () => {
    hooks.forEach((h) => h());
    flush();
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") onHide();
  });
  window.addEventListener("pagehide", onHide);
  return {
    add(event: AnnotatorEvent) {
      queue = [...queue, { retried: false, event: {
        id: crypto.randomUUID(), type: event.type, at: event.at, concept_id: event.concept_id,
        content_id: contentId,
        ...(event.paragraph_id ? { paragraph_id: event.paragraph_id } : {}),
        ...(event.words !== undefined ? { words: event.words } : {}),
        ...(event.ms !== undefined ? { ms: event.ms } : {}),
      } }];  // prettier-ignore
      timer ??= setTimeout(flush, FLUSH_MS);
    },
    beforeFlush(hook: () => void) {
      hooks.push(hook);
    },
  };
}

// Installed once per page (a second click re-runs this file; the guard keeps the first).
globalThis.__readlayer ??= { prepare, start };
