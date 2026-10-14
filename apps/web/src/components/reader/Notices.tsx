import { useEffect, useState } from "react";

import { Margo } from "../Margo";

/** The page stops calling: the reason, the original, and "Try again" when it may help. */
export function StopNotice({ message, url, onRetry }: { message: string; url: string; onRetry?: () => void }) {
  return (
    <div className="reader__notice reader__notice--stop" role="alert">
      <Margo mood="oops" size={28} />
      <p>{message}</p>
      <span className="reader__notice-acts">
        {onRetry && (
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Try again
          </button>
        )}
        <a className="btn btn--sm" href={url} target="_blank" rel="noopener noreferrer">
          Open original
          <span className="visually-hidden"> (opens in a new tab)</span>
        </a>
      </span>
    </div>
  );
}

/** Phase 2 in progress: the article is readable; say what's coming and how long it's been. */
export function PreparingNotice({ since, text }: { since: number; text: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const seconds = Math.round((Date.now() - since) / 1000);
  return (
    <p className="reader__notice reader__notice--working" role="status">
      <Margo mood="think" size={28} />
      {text} <span className="tnum">{seconds} s</span>
    </p>
  );
}
