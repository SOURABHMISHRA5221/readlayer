import type { ContentSummary } from "../../lib/api";
import { domainLabel, formatDate, readingMinutes, sourceName } from "../../lib/format";
import { ArticleImage } from "../ArticleImage";
import { Row } from "./Row";

/** A corpus article as a feed row (Topics and Saved tabs). */
export function LibraryRow({
  item, href, saved, onSave,
}: { item: ContentSummary; href: string; saved: boolean; onSave: () => void }) {  // prettier-ignore
  const date = formatDate(item.published);
  return (
    <Row
      source={sourceName(item.site)}
      context={item.domain ? `in ${domainLabel(item.domain)}` : ""}
      title={item.title}
      href={href}
      subtitle={item.description}
      time={`${readingMinutes(item.word_count)} min read${date ? ` · ${date}` : ""}`}
      newCount={item.concepts_new}
      saved={saved}
      onSave={onSave}
      thumbnail={
        item.image ? (
          <ArticleImage src={item.image} site={item.site} domain={item.domain} width={120} height={120} className="row__img" />
        ) : null
      }
    />
  );
}
