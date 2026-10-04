import { useState } from "react";

import { domainLabel, sourceMonogram } from "../lib/format";

interface ArticleImageProps {
  src: string | null;
  site: string;
  domain: string | null;
  /** Rendered size hint for the browser; the box itself is sized by CSS aspect-ratio. */
  width: number;
  height: number;
  priority?: boolean;
  className?: string;
}

/**
 * The publisher's own lead image, hotlinked with no referrer. The box always reserves its
 * aspect ratio, so nothing moves when the image arrives; a missing or broken image becomes a
 * typographic tile instead of a hole.
 */
export function ArticleImage({ src, site, domain, width, height, priority = false, className = "" }: ArticleImageProps) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const show = src && !failed;
  return (
    <div className={`media ${className}`} data-loaded={loaded || !show}>
      {show ? (
        <img
          src={src}
          alt=""
          width={width}
          height={height}
          loading={priority ? "eager" : "lazy"}
          fetchPriority={priority ? "high" : "auto"}
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="media__tile" aria-hidden="true">
          <span className="media__monogram">{sourceMonogram(site)}</span>
          {domain && <span className="media__domain">{domainLabel(domain)}</span>}
        </div>
      )}
    </div>
  );
}
