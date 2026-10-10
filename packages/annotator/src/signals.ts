/**
 * Reading signals (DESIGN §9) the annotator observes on its own: paragraph_dwell and
 * text_searched. Neither ever carries article text, only ids and counts. Also keeps the
 * annotator's controls out of copied text.
 */

import { indexText } from "./anchor";
import type { AnnotatorEvent } from "./types";
import { UI_ATTR } from "./ui";

export const MIN_DWELL_MS = 1000;
export const SEARCH_GAP_MS = 10_000;
const VISIBLE_RATIO = 0.5;

export interface SignalsOptions {
  /** Attribute naming a paragraph element. */
  paragraphAttribute: string;
  emit: (event: AnnotatorEvent) => void;
  /** The concept of a span or prompt mark the range overlaps, if any. */
  conceptIn: (range: Range) => string | null;
  /** Whether a paragraph has any span or prompt mark (markers don't count). */
  hasMarks: (paragraphId: string) => boolean;
  now?: () => number;
}

interface Dwell {
  id: string;
  words: number;
  visibleSince: number | null;
  ms: number;
  counted: boolean; // words sent once per page view
}

export class Signals {
  private readonly doc: Document;
  private readonly now: () => number;
  private readonly dwell = new Map<Element, Dwell>();
  private readonly lastSearch = new Map<string, number>();
  private observer: IntersectionObserver | null = null;

  constructor(
    private readonly root: HTMLElement,
    private readonly options: SignalsOptions,
  ) {
    this.doc = root.ownerDocument;
    this.now = options.now ?? (() => Date.now());
    root.addEventListener("copy", this.onCopy);
    root.addEventListener("contextmenu", this.onContextMenu);
    this.doc.addEventListener("visibilitychange", this.onVisibility);
    this.observeParagraphs();
  }

  /** Emit the dwell accumulated so far (hosts call this before sending a batch on hide). */
  flush(): void {
    const t = this.now();
    for (const d of this.dwell.values()) {
      if (d.visibleSince !== null) {
        d.ms += t - d.visibleSince;
        d.visibleSince = this.visible() ? t : null;
      }
      this.emitDwell(d);
    }
  }

  destroy(): void {
    this.flush();
    this.observer?.disconnect();
    this.root.removeEventListener("copy", this.onCopy);
    this.root.removeEventListener("contextmenu", this.onContextMenu);
    this.doc.removeEventListener("visibilitychange", this.onVisibility);
  }

  private visible(): boolean {
    return this.doc.visibilityState !== "hidden";
  }

  private observeParagraphs(): void {
    const IO = this.doc.defaultView?.IntersectionObserver;
    if (typeof IO !== "function") return;
    const attr = this.options.paragraphAttribute;
    this.observer = new IO(this.onIntersect, { threshold: VISIBLE_RATIO });
    this.root.querySelectorAll(`[${attr}]`).forEach((el) => {
      const id = el.getAttribute(attr);
      if (!id) return;
      const words = indexText(el).text.split(/\s+/).filter(Boolean).length;
      this.dwell.set(el, { id, words, visibleSince: null, ms: 0, counted: false });
      this.observer?.observe(el);
    });
  }

  private readonly onIntersect = (entries: IntersectionObserverEntry[]): void => {
    const t = this.now();
    for (const entry of entries) {
      const d = this.dwell.get(entry.target);
      if (!d) continue;
      const inView = entry.isIntersecting && entry.intersectionRatio >= VISIBLE_RATIO;
      if (inView && d.visibleSince === null && this.visible()) {
        d.visibleSince = t;
      } else if (!inView && d.visibleSince !== null) {
        d.ms += t - d.visibleSince;
        d.visibleSince = null;
        this.emitDwell(d);
      }
    }
  };

  private readonly onVisibility = (): void => {
    const t = this.now();
    for (const [el, d] of this.dwell) {
      if (!this.visible() && d.visibleSince !== null) {
        d.ms += t - d.visibleSince;
        d.visibleSince = null;
      } else if (this.visible() && d.visibleSince === null && this.inView(el)) {
        d.visibleSince = t;
      }
    }
  };

  private inView(el: Element): boolean {
    const view = this.doc.defaultView;
    if (!view) return false;
    const r = el.getBoundingClientRect();
    const shown = Math.min(r.bottom, view.innerHeight) - Math.max(r.top, 0);
    return r.height > 0 && shown / r.height >= VISIBLE_RATIO;
  }

  /** Sends the stretch just ended; one under MIN_DWELL_MS is a glance and is dropped. */
  private emitDwell(d: Dwell): void {
    const ms = d.ms;
    d.ms = 0;
    if (ms < MIN_DWELL_MS) return;
    this.options.emit({
      type: "paragraph_dwell",
      annotation_id: null,
      concept_id: null,
      at: new Date().toISOString(),
      paragraph_id: d.id,
      words: d.counted ? 0 : d.words,
      ms: Math.round(ms),
    });
    d.counted = true;
  }

  private selection(): Range | null {
    const sel = this.doc.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
    const range = sel.getRangeAt(0);
    return this.root.contains(range.commonAncestorContainer) ? range : null;
  }

  /** Article text in the range, leaving out the annotator's controls. */
  private articleText(range: Range): string {
    const { nodes } = indexText(this.root);
    let text = "";
    for (const node of nodes) {
      if (!range.intersectsNode(node)) continue;
      const from = node === range.startContainer ? range.startOffset : 0;
      const to = node === range.endContainer ? range.endOffset : node.data.length;
      text += node.data.slice(from, to);
    }
    return text;
  }

  private readonly onCopy = (e: ClipboardEvent): void => {
    const range = this.selection();
    if (!range) return;
    const text = this.articleText(range);
    // Copying across a marker or chip: put back exactly the article's words.
    const crossesUi = Array.from(this.root.querySelectorAll(`[${UI_ATTR}]`)).some((el) =>
      range.intersectsNode(el),
    );
    if (crossesUi && e.clipboardData) {
      e.clipboardData.setData("text/plain", text);
      e.preventDefault();
    }
    this.searched(range, text);
  };

  private readonly onContextMenu = (): void => {
    const range = this.selection();
    if (range) this.searched(range, this.articleText(range));
  };

  /** A look-up: on a marked term → that concept; on a paragraph with no marks → the paragraph
   * only (threshold_offset, DESIGN §5); otherwise nothing. The text itself is never sent. */
  private searched(range: Range, text: string): void {
    if (!text.trim()) return; // a selection of only our controls is not a look-up
    const attr = this.options.paragraphAttribute;
    const start = range.startContainer;
    const host = (start.nodeType === 1 ? (start as Element) : start.parentElement)?.closest(
      `[${attr}]`,
    );
    const paragraphId = host?.getAttribute(attr) ?? undefined;
    const concept = this.options.conceptIn(range);
    if (!concept && (!paragraphId || this.options.hasMarks(paragraphId))) return;
    const key = paragraphId ?? concept ?? "";
    const t = this.now();
    const last = this.lastSearch.get(key);
    if (last !== undefined && t - last < SEARCH_GAP_MS) return;
    this.lastSearch.set(key, t);
    this.options.emit({
      type: "text_searched",
      annotation_id: null,
      concept_id: concept,
      at: new Date().toISOString(),
      ...(paragraphId ? { paragraph_id: paragraphId } : {}),
    });
  }
}
