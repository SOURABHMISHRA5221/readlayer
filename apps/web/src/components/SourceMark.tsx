import { sourceMonogram, sourceName } from "../lib/format";

/** A typographic monogram, not the publisher's logo: we attribute, we don't impersonate. */
export function SourceMark({ site, withName = true }: { site: string; withName?: boolean }) {
  return (
    <span className="source">
      <span className="source__mark" aria-hidden="true">
        {sourceMonogram(site)}
      </span>
      {withName && <span className="source__name">{sourceName(site)}</span>}
    </span>
  );
}
