import { useState } from "react";

import type { ContentDetail } from "../../lib/api";
import { trackEvent } from "../../lib/events";
import { DENSITIES, type Density, type PersonaKey } from "../../lib/personas";
import { Bookmark, CopyLink, External, ThumbUp } from "../Icons";
import { Segmented } from "../Segmented";

interface Props {
  article: ContentDetail;
  persona: PersonaKey | null;
  density: Density;
  onDensity: (d: Density) => void;
  saved: boolean;
  onSave: () => void;
}

/** Sticky slim action bar under the byline (Design pass C6). */
export function ActionBar({ article, persona, density, onDensity, saved, onSave }: Props) {
  const [helped, setHelped] = useState(false);
  const [status, setStatus] = useState("");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setStatus("Link copied");
    } catch {
      setStatus("Couldn't copy the link");
    }
    setTimeout(() => setStatus(""), 2500);
  };
  return (
    <div className="actionbar" role="toolbar" aria-label="Article actions">
      <Segmented label="Notes" options={DENSITIES} value={density} onChange={onDensity} />
      <span className="actionbar__spacer" />
      <button
        type="button"
        className={`actionbar__helpful${helped ? " is-done" : ""}`}
        aria-pressed={helped}
        disabled={helped}
        onClick={() => {
          trackEvent("article_helpful", null, article.id, persona);
          setHelped(true);
          setStatus("Thanks, noted");
        }}
      >
        <ThumbUp />
        <span>{helped ? "Thanks" : "Helpful"}</span>
      </button>
      <button type="button" className="icon-btn" aria-pressed={saved} aria-label={saved ? "Saved" : "Save"} title={saved ? "Saved" : "Save"} onClick={onSave}>
        <Bookmark filled={saved} />
      </button>
      <button type="button" className="icon-btn" aria-label="Copy link" title="Copy link" onClick={copy}>
        <CopyLink />
      </button>
      <a className="icon-btn" href={article.url} target="_blank" rel="noopener noreferrer" aria-label="Open original (opens in a new tab)" title="Open original">
        <External />
      </a>
      <span className="visually-hidden" role="status" aria-live="polite">
        {status}
      </span>
    </div>
  );
}
