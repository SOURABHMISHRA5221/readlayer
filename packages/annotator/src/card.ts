/**
 * The concept card: one shared dialog, floated next to its mark with Floating UI, set in the
 * page margin as a sidenote when the host offers a margin column, or shown as a draggable
 * bottom sheet on touch and narrow screens. Filled with textContent only: annotation data is
 * never parsed as HTML.
 */

import {
  arrow,
  autoUpdate,
  computePosition,
  flip,
  offset,
  shift,
  size,
} from "@floating-ui/dom";

import type {
  AnnotationDebug,
  AnnotatorEventType,
  CardAnnotation,
  Explanation,
  FrameChoice,
  Frames,
  NextUpChip,
  NextUpFormat,
} from "./types";

export const CARD_LABEL = "Explanation — not the author's words";
export const BACKGROUND_LABEL = "Background";
export const AUTHOR_LABEL = "What the author is saying";
export const DEFINITION_LABEL = "Definition";
export const NEXT_UP_LABEL = "Up next";
const NEXT_VERB: Record<NextUpFormat, string> = { article: "Read", video: "Watch", podcast: "Listen" };
const REPORTED_TEXT = "Thanks. We've removed this explanation and will review it.";
const LOADING_TEXT = "Writing an explanation and checking it against the article…";
// A paragraph has no glossary definition to fall back on.
export const NO_EXPLANATION_TEXT =
  "No explanation passed our accuracy check for this paragraph, so we're not showing one.";

/** What the explanation area shows: nothing (no loader), loading, a result, or reported. */
export type ExplanationState = "none" | "loading" | "reported" | Explanation;
export const SHEET_QUERY = "(max-width: 639px)";
const C = "rl-card";
const GAP_PX = 10;
const EDGE_PX = 12;
const DISMISS_DRAG_PX = 80;
const MIN_HEIGHT_PX = 180;
const MAKE_ROOM_MS = 3000;
// Hosts with a fixed top bar set --rl-top-inset (px) so cards never slide under it.
const TOP_INSET_VAR = "--rl-top-inset";
const SVG_NS = "http://www.w3.org/2000/svg";

/** "inline": in the host's own box, in normal flow (a landing demo that keeps one note open). */
export type CardMode = "float" | "sheet" | "sidenote" | "inline";

/** Where a sidenote goes: the margin column's left edge and usable width, in viewport px. */
export interface SidenoteBox {
  left: number;
  width: number;
}

export interface CardHandlers {
  onAction: (type: AnnotatorEventType) => void;
  onDismiss: () => void;
  /** "Say it simpler" (-1), "Go deeper" (+1) or back to the reader's own level (0). */
  onShift?: (shift: -1 | 0 | 1) => void;
  /** Demo cards (a landing page): one call to action replaces Knew this / Helpful / This is wrong. */
  demo?: { label: string; onClick: () => void };
  /** Overrides for the restatement's heading and the footer line (a transcript: "speaker"). */
  labels?: CardLabels;
  /** The other analogy frame was chosen (decision 67 A4). */
  onFrame?: (frame: FrameChoice) => void;
  /** An "Up next" chip was clicked (decision 67 N2). */
  onNextUp?: (chip: NextUpChip) => void;
}

export interface CardLabels {
  author?: string;
  card?: string;
}

const BANDS = ["unaware", "heard of", "understands", "can explain"] as const;
const PITCH: Record<string, string> = {
  unaware: "New to you, so this note starts from zero",
  "heard of": "You've heard of this, so it skips the basics",
  understands: "You understand this, so it's a one-line refresher",
  "can explain": "You know this well, so it goes straight to the detail",
};
export const BUILDS_ON_LABEL = "Builds on";

let cardCount = 0;

export class Card {
  readonly el: HTMLDivElement;
  private readonly scrim: HTMLDivElement;
  private readonly arrowEl: HTMLDivElement;
  private readonly domain: HTMLParagraphElement;
  private readonly title: HTMLParagraphElement;
  private definitionText = "";
  private readonly prereqs: HTMLDivElement;
  private readonly prereqList: HTMLUListElement;
  private readonly debug: HTMLDListElement;
  private readonly explain: HTMLDivElement;
  private readonly frame: HTMLSpanElement;
  private readonly bgLabel: HTMLElement;
  private readonly bgSection: HTMLElement;
  private readonly knew: HTMLButtonElement;
  private readonly says: HTMLElement;
  private readonly background: HTMLParagraphElement;
  private readonly authorSays: HTMLParagraphElement;
  private readonly status: HTMLParagraphElement;
  private readonly pitch: HTMLDivElement;
  private readonly meter: HTMLSpanElement;
  private readonly pitchText: HTMLSpanElement;
  private readonly depth: HTMLDivElement;
  private readonly simpler: HTMLButtonElement;
  private readonly deeper: HTMLButtonElement;
  private shiftEnabled = false;
  // Decision 67: the frame toggle and the Up next chips.
  private framesEnabled = false;
  private frameChoice: FrameChoice = "pick";
  private lastFrames: Frames | null = null;
  private readonly frameGroup: HTMLDivElement;
  private readonly frameOptions: [HTMLButtonElement, HTMLButtonElement];
  private readonly next: HTMLDivElement;
  private readonly nextRow: HTMLUListElement;
  private readonly chipsAllowed: boolean;
  private readonly onNextUp?: (chip: NextUpChip) => void;
  private stopNextWatch: (() => void) | null = null;
  private shift: -1 | 0 | 1 = 0;
  private kind: string = "span";
  private sidenote: SidenoteBox | null = null;
  private readonly body: HTMLDivElement;
  // Until when a card opened on purpose (click, tap, keyboard) may scroll the page once to make
  // room, rather than hiding the author block below a scroll. Short, so a slow generation never
  // moves the page long after the click; the fade on the body covers that case.
  private makeRoomUntil = 0;
  private anchor: HTMLElement | null = null;
  private readonly report: HTMLButtonElement;
  private readonly buttons: HTMLButtonElement[];
  private stopAutoUpdate: (() => void) | null = null;
  private mode: CardMode = "float";
  // Inline cards stay hidden until their explanation settles, so no skeleton is ever shown.
  private pending = false;

  constructor(
    private readonly doc: Document,
    handlers: CardHandlers,
    /** The inline host: the card lives in it, in flow, at every width (no popover or sheet). */
    private readonly inline: HTMLElement | null = null,
  ) {
    const id = `rl-card-${++cardCount}`;
    this.el = el(doc, "div", C);
    Object.assign(this.el, { id, hidden: true, tabIndex: -1 });
    // Always open in the page, an inline card is a labelled group, not a dialog.
    this.el.setAttribute("role", inline ? "group" : "dialog");
    this.el.setAttribute("aria-labelledby", `${id}-title`);
    this.el.setAttribute("aria-describedby", `${id}-bg`);

    this.scrim = el(doc, "div", "rl-scrim");
    this.scrim.hidden = true;
    this.scrim.addEventListener("click", handlers.onDismiss);

    const handle = el(doc, "div", `${C}__handle`);
    handle.setAttribute("aria-hidden", "true");
    this.enableDrag(handle, handlers.onDismiss);

    this.arrowEl = el(doc, "div", `${C}__arrow`);
    this.arrowEl.setAttribute("aria-hidden", "true");

    this.domain = el(doc, "p", `${C}__domain`);
    this.title = el(doc, "p", `${C}__title`);
    this.title.id = `${id}-title`;

    this.prereqs = el(doc, "div", `${C}__prereqs`);
    const prereqLabel = el(doc, "p", `${C}__prereq-label`);
    prereqLabel.textContent = BUILDS_ON_LABEL;
    prereqLabel.id = `${id}-prereq`;
    this.prereqList = el(doc, "ul", `${C}__chips`);
    this.prereqList.setAttribute("aria-labelledby", prereqLabel.id);
    this.prereqs.append(prereqLabel, this.prereqList);

    this.debug = el(doc, "dl", `${C}__debug`);

    // How the note is pitched: a 4-step meter (decorative) and one plain line (Gloss).
    this.pitch = el(doc, "div", `${C}__pitch`);
    this.meter = el(doc, "span", `${C}__meter`);
    this.meter.setAttribute("aria-hidden", "true");
    for (let i = 0; i < BANDS.length; i++) this.meter.append(el(doc, "span", ""));
    this.pitchText = el(doc, "span", "");
    this.pitch.append(this.meter, this.pitchText);
    this.pitch.hidden = true;

    // "Say it simpler" / "Go deeper": opt-in for hosts that can load another band.
    this.depth = el(doc, "div", `${C}__depth`);
    this.simpler = el(doc, "button", "rl-btn rl-btn--ghost rl-btn--depth");
    this.deeper = el(doc, "button", "rl-btn rl-btn--ghost rl-btn--depth");
    for (const [b, shift] of [[this.simpler, -1], [this.deeper, 1]] as const) {
      b.type = "button";
      b.addEventListener("click", () => handlers.onShift?.(this.shift === shift ? 0 : shift));
    }
    this.depth.append(this.simpler, this.deeper);
    this.depth.hidden = true;

    // One panel holds the background: the glossary definition at once (and as the fallback),
    // replaced in place by the reader's verified Background, which is ours (their frame, the
    // only place for an analogy), so it sits recessed on a tint with the frame named. The
    // restatement of the author is the primary block, ruled in the accent that marks the text.
    // Labels never move while loading; only bodies swap, so nothing jumps.
    this.explain = el(doc, "div", `${C}__explain`);
    this.frame = el(doc, "span", `${C}__frame`);
    this.background = el(doc, "p", `${C}__text`);
    this.background.id = `${id}-bg`;
    this.authorSays = el(doc, "p", `${C}__text`);
    const bg = section(doc, `${C}__bg`, BACKGROUND_LABEL, this.background, 0, this.frame);
    this.bgLabel = bg.querySelector(`.${C}__section-label`)!;
    this.bgSection = bg;
    // "Your pick · X" / "For you": a two-option radio group under the Background's label.
    this.frameGroup = el(doc, "div", "rl-frame");
    this.frameGroup.setAttribute("role", "radiogroup");
    this.frameGroup.setAttribute("aria-label", "Analogy");
    this.frameGroup.hidden = true;
    const options = (["pick", "for_you"] as const).map((choice) => {
      const b = el(doc, "button", "rl-frame__option");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.dataset.frame = choice;
      b.addEventListener("click", () => {
        if (b.getAttribute("aria-checked") !== "true") handlers.onFrame?.(choice);
      });
      b.addEventListener("keydown", (e) => {
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
        e.preventDefault();
        const other = choice === "pick" ? this.frameOptions[1] : this.frameOptions[0];
        other.focus();
        handlers.onFrame?.(other.dataset.frame as FrameChoice);
      });
      return b;
    });
    this.frameOptions = [options[0]!, options[1]!];
    this.frameGroup.append(...this.frameOptions);
    bg.querySelector(`.${C}__section-head`)!.after(this.frameGroup);
    this.says = section(doc, `${C}__says`, handlers.labels?.author ?? AUTHOR_LABEL, this.authorSays, 1);
    const says = this.says;
    const note = el(doc, "p", `${C}__loading-note`);
    note.textContent = LOADING_TEXT;
    note.setAttribute("aria-hidden", "true"); // the status line announces it
    says.querySelector(`.${C}__skeleton`)?.append(note);
    this.explain.append(bg, this.depth, says);
    // Announces loading to screen readers; shows the report confirmation.
    this.status = el(doc, "p", `${C}__status`);
    this.status.setAttribute("role", "status");

    const footer = el(doc, "div", `${C}__footer`);
    const knew = button(doc, "knew_this", "rl-btn rl-btn--ghost");
    knew.textContent = "Knew this";
    this.knew = knew;
    // A visible word, not a bare thumb: what the button records is unambiguous (M5 review).
    const helpful = button(doc, "explain_helpful", "rl-btn rl-btn--ghost rl-btn--helpful");
    const helpfulText = el(doc, "span", "");
    helpfulText.textContent = "Helpful";
    helpful.append(thumbIcon(doc), helpfulText);
    this.report = button(doc, "report_wrong", "rl-btn rl-btn--ghost rl-btn--quiet");
    this.report.textContent = "This is wrong";
    this.buttons = [knew, this.report, helpful];
    for (const b of this.buttons) {
      b.addEventListener("click", () => {
        b.setAttribute("aria-pressed", "true");
        handlers.onAction(b.dataset.action as AnnotatorEventType);
      });
    }
    const actions = el(doc, "div", `${C}__actions`);
    actions.append(knew, this.report, helpful);
    if (handlers.demo) {
      // A demo card records nothing: its only action leads to the real thing.
      const cta = el(doc, "button", "rl-btn rl-btn--demo");
      cta.type = "button";
      cta.textContent = handlers.demo.label;
      cta.addEventListener("click", handlers.demo.onClick);
      for (const b of this.buttons) b.hidden = true;
      this.buttons.length = 0;
      this.buttons.push(cta);
      actions.replaceChildren(cta);
    }
    const label = el(doc, "p", `${C}__note`);
    label.textContent = handlers.labels?.card ?? CARD_LABEL;
    footer.append(actions, label);

    // Up next (decision 67 N2): at the end of the scrolling body, not the pinned footer, so it
    // never squeezes the phone sheet. Never on demo or inline cards.
    this.chipsAllowed = !handlers.demo && !inline;
    this.onNextUp = handlers.onNextUp;
    this.next = el(doc, "div", `${C}__next`);
    const nextLabel = el(doc, "p", `${C}__next-label`);
    nextLabel.textContent = NEXT_UP_LABEL;
    nextLabel.id = `${id}-next`;
    this.nextRow = el(doc, "ul", `${C}__next-row`);
    this.nextRow.setAttribute("aria-labelledby", nextLabel.id);
    this.next.append(nextLabel, this.nextRow);
    this.next.hidden = true;

    // The body scrolls when the card is taller than the room it has; the actions stay pinned.
    this.body = el(doc, "div", `${C}__body`);
    this.body.append(this.domain, this.title, this.pitch, this.prereqs, this.explain, this.status, this.debug, this.next);
    this.body.addEventListener("scroll", () => this.markOverflow(), { passive: true });
    this.el.append(handle, this.arrowEl, this.body, footer);
    if (inline) inline.append(this.el);
    else doc.body.append(this.scrim, this.el);
  }

  get id(): string {
    return this.el.id;
  }

  get isOpen(): boolean {
    return !this.el.hidden;
  }

  focusables(): HTMLElement[] {
    const depth = this.depth.hidden ? [] : [this.simpler, this.deeper];
    const frame = this.frameGroup.hidden ? [] : this.frameOptions.filter((b) => b.tabIndex === 0);
    const chips = this.next.hidden ? [] : Array.from(this.nextRow.querySelectorAll<HTMLElement>("a"));
    return [...frame, ...depth, ...this.buttons, ...chips].filter(
      (b) => !(b as HTMLButtonElement).disabled && !b.hidden,
    );
  }

  /** The host can load the other analogy frame (AnnotatorOptions.loadFramed). */
  enableFrames(on: boolean): void {
    this.framesEnabled = on;
  }

  setFrameChoice(choice: FrameChoice): void {
    this.frameChoice = choice;
  }

  /** Fill the Up next row; returns the ids shown (none when not allowed or empty). */
  setNextUp(chips: readonly NextUpChip[]): string[] {
    this.stopNextWatch?.();
    this.stopNextWatch = null;
    const shown = this.chipsAllowed ? chips.slice(0, 3) : [];
    this.next.hidden = shown.length === 0;
    this.nextRow.replaceChildren(
      ...shown.map((chip) => {
        const li = el(this.doc, "li", "");
        const a = el(this.doc, "a", "rl-next");
        a.href = chip.href;
        if (/^https?:/.test(chip.href)) Object.assign(a, { target: "_blank", rel: "noopener noreferrer" });
        a.dataset.format = chip.format;
        const verb = el(this.doc, "span", "rl-next__verb");
        verb.textContent = NEXT_VERB[chip.format];
        const title = el(this.doc, "span", "rl-next__title");
        title.textContent = chip.title;
        const meta = el(this.doc, "span", "rl-next__meta");
        meta.textContent = chip.minutes ? `${chip.source} · ${chip.minutes} min` : chip.source;
        a.append(verb, title, meta);
        a.addEventListener("click", (e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // new tab: the link's own
          e.preventDefault();
          this.onNextUp?.(chip);
        });
        li.append(a);
        return li;
      }),
    );
    return shown.map((c) => c.id);
  }

  /**
   * `seen` once, when the chip row is first mostly visible inside the card body (it sits at the
   * end of a scrolling body, often below the fold on a phone). Without IntersectionObserver it
   * runs at once. Stopped when the card hides or its chips change.
   */
  watchNextUp(seen: () => void): void {
    this.stopNextWatch?.();
    this.stopNextWatch = null;
    if (this.next.hidden) return;
    const Observer = this.doc.defaultView?.IntersectionObserver;
    if (!Observer) {
      seen();
      return;
    }
    const observer = new Observer(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        observer.disconnect();
        this.stopNextWatch = null;
        seen();
      },
      { root: this.body, threshold: 0.6 },
    );
    observer.observe(this.next);
    this.stopNextWatch = () => observer.disconnect();
  }

  /** The two-option frame toggle, or nothing (decision 67 A4). */
  private fillFrames(frames: Frames | null, checked: FrameChoice): boolean {
    const on = Boolean(this.framesEnabled && frames?.for_you && frames.for_you !== frames.pick);
    this.frameGroup.hidden = !on;
    if (!on || !frames) return false;
    const [pick, forYou] = this.frameOptions;
    pick.textContent = frames.pick ? `Your pick · ${capitalise(frames.pick)}` : "No analogy";
    forYou.textContent = "For you"; // Sourabh, 2026-10-17: the frame's name isn't shown
    for (const b of this.frameOptions) {
      const isChecked = b.dataset.frame === checked;
      b.setAttribute("aria-checked", String(isChecked));
      b.tabIndex = isChecked ? 0 : -1;
    }
    return true;
  }

  /** The host can load other bands (AnnotatorOptions.loadShifted). */
  enableShift(on: boolean): void {
    this.shiftEnabled = on;
  }

  setShift(shift: -1 | 0 | 1): void {
    this.shift = shift;
  }

  fill(a: CardAnnotation, pressed: ReadonlySet<AnnotatorEventType>): void {
    // Paragraph cards have no concept: nothing to "know", no prerequisites.
    this.el.dataset.kind = a.kind;
    this.kind = a.kind;
    this.shift = 0;
    this.lastFrames = null; // another note: its frames arrive with its explanation
    this.knew.hidden = a.kind === "paragraph";
    this.domain.textContent = a.domain ?? "";
    this.domain.hidden = !a.domain;
    this.title.textContent = a.label;
    this.definitionText = a.definition;
    const prereqs = a.prerequisites.slice(0, 3);
    this.prereqs.hidden = prereqs.length === 0;
    this.prereqList.replaceChildren(
      ...prereqs.map((label) => {
        const li = el(this.doc, "li", "rl-chip");
        li.textContent = label;
        return li;
      }),
    );
    fillDebug(this.debug, a.debug ?? null);
    for (const b of this.buttons) {
      b.setAttribute("aria-pressed", String(pressed.has(b.dataset.action as AnnotatorEventType)));
    }
    this.setExplanation(pressed.has("report_wrong") ? "reported" : "none");
  }

  /**
   * Fill the panels. Loading: the definition in the Background panel, a skeleton for the
   * author. Verified: the reader's Background replaces the definition in place. Otherwise
   * (definition only, no loader, reported): the panel is labelled Definition and the author
   * block goes. "This is wrong" only exists next to a verified explanation.
   */
  setExplanation(state: ExplanationState): void {
    const verified = typeof state === "object" && state.kind === "verified";
    const loading = state === "loading";
    this.pending = loading;
    // Skeleton → text: grow from the old height instead of snapping.
    const from = !this.el.hidden ? this.explain.offsetHeight : 0;
    // An inline card is revealed only now, after `from`: its first appearance never grows from a
    // skeleton, so the host's static copy can swap with it without a jump (decision 46e).
    if (!loading && this.mode === "inline" && this.inline && this.el.hidden && this.anchor) this.el.hidden = false;
    const before = this.background.textContent;
    this.explain.dataset.state = loading ? "loading" : "ready";
    this.explain.setAttribute("aria-busy", String(loading));
    this.explain.hidden = !verified && !loading && !this.definitionText;
    // A verified card may come without a Background (it failed its own check): the definition
    // stays in that panel, labelled as such.
    const background = verified ? state.background : null;
    this.bgLabel.textContent =
      background || (loading && this.definitionText) ? BACKGROUND_LABEL : DEFINITION_LABEL;
    this.background.textContent = background ?? this.definitionText;
    this.bgSection.hidden = !this.background.textContent;
    this.says.hidden = !(verified || loading);
    this.authorSays.textContent = verified ? (state.author_says ?? "") : "";
    if (!loading) this.fillPitch(verified ? state : null); // keep the buttons under focus while loading
    if (verified) this.lastFrames = state.frames ?? null;
    const frames = verified && background ? (state.frames ?? null) : loading ? this.lastFrames : null;
    const toggled = this.fillFrames(frames, loading || !frames ? this.frameChoice : frames.used);
    const frame = background && verified && !toggled ? state.analogy_domain : null;
    this.frame.textContent = frame ? `Analogy · ${frame}` : "";
    this.frame.hidden = !frame;
    const empty = !verified && !loading && state !== "reported" && !this.definitionText;
    this.status.textContent =
      state === "reported"
        ? REPORTED_TEXT
        : loading
          ? LOADING_TEXT
          : empty && state !== "none"
            ? NO_EXPLANATION_TEXT
            : "";
    this.status.classList.toggle(
      `${C}__status--visible`,
      state === "reported" || (empty && state !== "none"),
    );
    const reported = this.report.getAttribute("aria-pressed") === "true";
    this.report.disabled = !verified;
    this.report.hidden = !(verified || loading || reported);
    if (from && verified) this.grow(from, before !== this.background.textContent);
    this.markOverflow();
    // A capped card doesn't resize when its content arrives, so check for room here too.
    if (!this.el.hidden) this.maybeMakeRoom();
  }

  /** Level meter, pitch line and depth buttons from the band the Background was written for. */
  private fillPitch(e: Explanation | null): void {
    const band = e?.band;
    const i = band ? BANDS.indexOf(band as (typeof BANDS)[number]) : -1;
    const span = this.kind === "span";
    this.pitch.hidden = !span || i < 0 || !e?.background;
    if (!this.pitch.hidden) {
      Array.from(this.meter.children).forEach((seg, k) => seg.classList.toggle("on", k <= i));
      this.pitchText.textContent =
        this.shift === -1 ? "Simpler than your level" : this.shift === 1 ? "Deeper than your level" : (PITCH[band ?? ""] ?? "");
    }
    const simplerOk = this.shift === -1 || Boolean(e?.can_simpler);
    const deeperOk = this.shift === 1 || Boolean(e?.can_deeper);
    // A rejected shifted Background still offers the way back to the reader's own level.
    this.depth.hidden = !(this.shiftEnabled && span && (e?.background || this.shift !== 0) && (simplerOk || deeperOk));
    this.simpler.hidden = !simplerOk;
    this.deeper.hidden = !deeperOk;
    this.simpler.textContent = this.shift === -1 ? "Back to my level" : "Say it simpler";
    this.deeper.textContent = this.shift === 1 ? "Back to my level" : "Go deeper";
    this.simpler.setAttribute("aria-pressed", String(this.shift === -1));
    this.deeper.setAttribute("aria-pressed", String(this.shift === 1));
  }

  private grow(from: number, swapped: boolean): void {
    const view = this.doc.defaultView;
    const to = this.explain.offsetHeight;
    const still = view?.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    if (still || !to || !this.explain.animate) return;
    if (swapped) this.background.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 260 });
    if (Math.abs(to - from) < 2) return;
    this.explain.animate(
      [{ height: `${from}px`, overflow: "hidden" }, { height: `${to}px`, overflow: "hidden" }],
      { duration: 240, easing: "cubic-bezier(0.2, 0, 0, 1)" },
    );
  }

  show(
    anchor: HTMLElement,
    mode: CardMode,
    sidenote: SidenoteBox | null = null,
    makeRoom = false,
  ): void {
    this.stopAutoUpdate?.();
    this.mode = mode;
    this.makeRoomUntil = makeRoom && mode === "float" ? Date.now() + MAKE_ROOM_MS : 0;
    this.anchor = anchor;
    this.sidenote = mode === "sidenote" ? sidenote : null;
    this.el.style.width = this.sidenote ? `${this.sidenote.width}px` : "";
    this.el.style.maxHeight = "";
    this.el.dataset.mode = mode;
    this.el.style.transform = "";
    if (mode === "inline") {
      // In flow in the host: no position, no scrim; shown once the explanation is in.
      Object.assign(this.el.style, { top: "", left: "" });
      this.el.hidden = this.pending;
      if (!this.el.hidden) this.markOverflow(); // a scrolling inline body must be reachable
      return;
    }
    this.el.hidden = false;
    this.scrim.hidden = mode !== "sheet";
    if (mode === "sheet") {
      Object.assign(this.el.style, { top: "", left: "" });
      return;
    }
    this.stopAutoUpdate = autoUpdate(anchor, this.el, () => void this.place(anchor));
  }

  /** A quiet card's status line isn't a live region (a host opened it; nobody asked). */
  setQuiet(quiet: boolean): void {
    if (quiet) this.status.removeAttribute("role");
    else this.status.setAttribute("role", "status");
  }

  hide(): void {
    this.stopNextWatch?.();
    this.stopNextWatch = null;
    this.stopAutoUpdate?.();
    this.stopAutoUpdate = null;
    this.anchor = null;
    this.el.hidden = true;
    this.scrim.hidden = true;
  }

  contains(node: Node | null): boolean {
    return !!node && (this.el.contains(node) || node === this.scrim);
  }

  destroy(): void {
    this.hide();
    this.el.remove();
    this.scrim.remove();
  }

  private async place(anchor: HTMLElement): Promise<void> {
    if (this.sidenote) {
      this.placeSidenote(anchor, this.sidenote);
      return;
    }
    const padding = { top: this.topInset(), right: EDGE_PX, bottom: EDGE_PX, left: EDGE_PX };
    const { x, y, placement, middlewareData } = await computePosition(anchor, this.el, {
      strategy: "fixed",
      placement: "bottom-start",
      middleware: [
        offset(GAP_PX),
        // Below or above, whichever has more room; then cap the height to that room.
        flip({ padding, fallbackStrategy: "bestFit" }),
        shift({ padding }),
        size({
          padding,
          apply: ({ availableHeight }) => {
            this.el.style.maxHeight = `${Math.max(MIN_HEIGHT_PX, availableHeight)}px`;
          },
        }),
        arrow({ element: this.arrowEl, padding: 14 }),
      ],
    });
    if (this.el.hidden || this.mode !== "float") return;
    Object.assign(this.el.style, { left: `${x}px`, top: `${y}px` });
    this.markOverflow();
    this.maybeMakeRoom();
    this.el.dataset.placement = placement;
    const side = placement.split("-")[0];
    const a = middlewareData.arrow;
    Object.assign(this.arrowEl.style, {
      left: a?.x != null ? `${a.x}px` : "",
      top: a?.y != null ? `${a.y}px` : "",
      [side === "bottom" ? "top" : "bottom"]: "-6px",
      [side === "bottom" ? "bottom" : "top"]: "",
    });
  }

  /** In the margin, level with the mark's line, kept inside the viewport; the arrow points
   * back at the line. */
  private placeSidenote(anchor: HTMLElement, box: SidenoteBox): void {
    const view = this.doc.defaultView;
    if (!view || this.el.hidden) return;
    const mark = anchor.getBoundingClientRect();
    const inset = this.topInset();
    this.el.style.maxHeight = `${view.innerHeight - inset - EDGE_PX}px`;
    const height = this.el.offsetHeight;
    const top = Math.max(inset, Math.min(mark.top - 14, view.innerHeight - height - EDGE_PX));
    Object.assign(this.el.style, { left: `${box.left}px`, top: `${top}px` });
    this.el.dataset.placement = "right";
    const arrowY = Math.max(10, Math.min(mark.top + mark.height / 2 - top - 6, height - 22));
    Object.assign(this.arrowEl.style, { left: "-7px", top: `${arrowY}px`, bottom: "" });
  }

  /**
   * Fade the body's bottom edge while there is more to scroll. A body that scrolls at all is a
   * labelled, focusable region, so keyboard readers can scroll it too (axe
   * scrollable-region-focusable); one that fits is plain again.
   */
  private markOverflow(): void {
    const b = this.body;
    const more = b.scrollHeight - b.clientHeight - b.scrollTop > 4;
    b.classList.toggle(`${C}__body--more`, more);
    if (b.scrollHeight > b.clientHeight + 1) {
      b.tabIndex = 0;
      b.setAttribute("role", "region");
      b.setAttribute("aria-label", "Note");
    } else {
      b.removeAttribute("tabindex");
      b.removeAttribute("role");
      b.removeAttribute("aria-label");
    }
  }

  private maybeMakeRoom(): void {
    const ready = this.explain.hidden || this.explain.dataset.state === "ready";
    if (!ready || !this.makeRoomUntil || !this.anchor || this.mode !== "float") return;
    if (Date.now() < this.makeRoomUntil) this.scrollForRoom(this.anchor);
    this.makeRoomUntil = 0;
  }

  /** If the filled card still doesn't fit, bring its line up under the top bar so the card
   * opens below it with the most room the screen has. Once per deliberate open. */
  private scrollForRoom(anchor: HTMLElement): void {
    const view = this.doc.defaultView;
    if (!view || this.body.scrollHeight - this.body.clientHeight <= 0) return;
    const shift = anchor.getBoundingClientRect().top - this.topInset() - GAP_PX;
    if (shift <= 1) return;
    const reduced = view.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    view.scrollBy({ top: shift, behavior: reduced ? "auto" : "smooth" });
  }

  private topInset(): number {
    const view = this.doc.defaultView;
    const raw = view?.getComputedStyle(this.doc.documentElement).getPropertyValue(TOP_INSET_VAR);
    const px = Number.parseFloat(raw ?? "");
    return Number.isFinite(px) && px > EDGE_PX ? px : EDGE_PX;
  }

  /** Swipe the sheet down by its handle to dismiss it. */
  private enableDrag(handle: HTMLElement, dismiss: () => void): void {
    let startY: number | null = null;
    let dy = 0;
    handle.addEventListener("pointerdown", (e) => {
      if (this.mode !== "sheet") return;
      startY = e.clientY;
      dy = 0;
      handle.setPointerCapture?.(e.pointerId);
      this.el.classList.add(`${C}--dragging`);
    });
    handle.addEventListener("pointermove", (e) => {
      if (startY === null) return;
      dy = Math.max(0, e.clientY - startY);
      this.el.style.transform = `translateY(${dy}px)`;
    });
    const end = () => {
      if (startY === null) return;
      startY = null;
      this.el.classList.remove(`${C}--dragging`);
      this.el.style.transform = "";
      if (dy > DISMISS_DRAG_PX) dismiss();
    };
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }
}

function capitalise(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function section(
  doc: Document,
  className: string,
  label: string,
  body: HTMLElement,
  lines: number,
  tag?: HTMLElement,
): HTMLElement {
  const wrap = el(doc, "section", `${C}__section ${className}`);
  const head = el(doc, "div", `${C}__section-head`);
  const heading = el(doc, "p", `${C}__section-label`);
  heading.textContent = label;
  head.append(heading, ...(tag ? [tag] : []));
  wrap.append(head);
  if (lines > 0) {
    const skeleton = el(doc, "div", `${C}__skeleton`);
    skeleton.setAttribute("aria-hidden", "true");
    skeleton.append(...Array.from({ length: lines }, () => el(doc, "span", `${C}__skeleton-line`)));
    wrap.append(skeleton);
  }
  wrap.append(body);
  return wrap;
}

function fillDebug(dl: HTMLDListElement, debug: AnnotationDebug | null): void {
  dl.replaceChildren();
  dl.hidden = debug === null;
  if (!debug) return;
  const rows: [string, string][] = [
    ["p_know", debug.p_know.toFixed(3)],
    ["salience", debug.salience.toFixed(2)],
    ["span_score", debug.span_score.toFixed(3)],
    ["domain", debug.domain],
    ["difficulty", debug.base_difficulty.toFixed(2)],
  ];
  for (const [k, v] of rows) {
    const dt = el(dl.ownerDocument, "dt", "");
    dt.textContent = k;
    const dd = el(dl.ownerDocument, "dd", "");
    dd.textContent = v;
    dl.append(dt, dd);
  }
}

function button(doc: Document, action: AnnotatorEventType, className: string): HTMLButtonElement {
  const b = el(doc, "button", className);
  b.type = "button";
  b.dataset.action = action;
  b.setAttribute("aria-pressed", "false");
  return b;
}

function thumbIcon(doc: Document): SVGSVGElement {
  const svg = doc.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = doc.createElementNS(SVG_NS, "path");
  path.setAttribute(
    "d",
    "M6.5 8.5 9.4 3.2a1.6 1.6 0 0 1 3 .9l-.5 3.4h3.6a1.8 1.8 0 0 1 1.8 2.1l-1 5.4a2 2 0 0 1-2 1.6H6.5m0-8.1v8.1m0-8.1H4a1 1 0 0 0-1 1v6.1a1 1 0 0 0 1 1h2.5",
  );
  for (const [k, v] of Object.entries({
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.5",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  })) {
    path.setAttribute(k, v);
  }
  svg.append(path);
  return svg;
}

function el<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  className: string,
): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  return node;
}
