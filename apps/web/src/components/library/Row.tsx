import type { ReactNode } from "react";

import { navigate } from "../../lib/router";
import { Bookmark, LessIcon } from "../Icons";

export interface RowProps {
  source: string;
  context: string; // "in Environment · video"
  title: string;
  href: string;
  external?: boolean; // opens the original in a new tab
  onOpen?: () => void; // "Read here" for web articles
  subtitle?: string | null;
  why?: ReactNode;
  time: string;
  newCount: number;
  goal?: string | null;
  saved?: boolean | null; // null: this row can't be saved (no library id)
  onSave?: () => void;
  onLess?: () => void;
  thumbnail?: ReactNode;
  busy?: boolean;
  error?: string | null;
}

/** One feed row (Design pass C5): source line, bold title, serif subtitle, quiet actions. */
export function Row(p: RowProps) {
  const initial = (p.source.replace(/^(www\.|the\s+)/i, "")[0] ?? "?").toUpperCase();
  return (
    <article className="row" aria-busy={p.busy || undefined}>
      <div className="row__body">
        <p className="row__src">
          <span className="row__fav" aria-hidden="true">
            {initial}
          </span>
          <span className="row__source">{p.source}</span>
          <span className="row__context">{p.context}</span>
        </p>
        <h3 className="row__title">
          <a
            href={p.href}
            target={p.external ? "_blank" : undefined}
            rel={p.external ? "noopener noreferrer" : undefined}
            onClick={(e) => {
              if (p.external || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
              e.preventDefault();
              if (p.onOpen) p.onOpen();
              else {
                navigate(p.href);
                window.scrollTo(0, 0);
              }
            }}
          >
            {p.title}
            {p.external && <span className="visually-hidden"> (opens in a new tab)</span>}
          </a>
        </h3>
        {p.subtitle && <p className="row__sub">{p.subtitle}</p>}
        {p.why && <p className="row__why">{p.why}</p>}
        <div className="row__meta">
          <span className="tnum">{p.busy ? "Opening…" : p.time}</span>
          {p.newCount > 0 && (
            <span className="row__new">
              {p.newCount} {p.newCount === 1 ? "idea" : "ideas"} new to you
            </span>
          )}
          {p.goal && <span className="row__goal">Helps your goal: {p.goal}</span>}
          <span className="row__acts">
            {p.saved !== null && p.saved !== undefined && p.onSave && (
              <button
                type="button"
                className="icon-btn"
                aria-pressed={p.saved}
                aria-label={p.saved ? `Saved: ${p.title}` : `Save: ${p.title}`}
                title={p.saved ? "Saved" : "Save"}
                onClick={p.onSave}
              >
                <Bookmark filled={p.saved} />
              </button>
            )}
            {p.onLess && (
              <button
                type="button"
                className="icon-btn"
                aria-label={`Show less like this: ${p.title}`}
                title="Show less like this"
                onClick={p.onLess}
              >
                <LessIcon />
              </button>
            )}
          </span>
        </div>
        {p.error && (
          <p className="row__error" role="alert">
            {p.error}
          </p>
        )}
      </div>
      {p.thumbnail && <div className="row__thumb">{p.thumbnail}</div>}
    </article>
  );
}
