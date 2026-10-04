import { sourceName, sourceTone } from "../lib/format";

export function SourceBadge({ site }: { site: string }) {
  return (
    <span className="source-badge" data-tone={sourceTone(site)}>
      {sourceName(site)}
    </span>
  );
}
