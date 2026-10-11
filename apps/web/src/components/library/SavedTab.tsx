import type { ContentSummary } from "../../lib/api";
import { StateView } from "../StateView";
import { LibraryRow } from "./libraryRows";

/** Saved articles (Design pass A6): lazy chunk of the library page. */
export default function SavedTab({
  items, href, onToggle,
}: { items: ContentSummary[] | null; href: (id: string) => string; onToggle: (id: string) => void }) {  // prettier-ignore
  if (items === null) return <p className="feedtab__note" role="status">Loading your saved articles…</p>;
  if (!items.length)
    return (
      <StateView title="Nothing saved yet" margo="oops">
        Tap the bookmark on any article in Topics to keep it here for later.
      </StateView>
    );
  return (
    <ul className="rows">
      {items.map((item) => (
        <li key={item.id}>
          <LibraryRow item={item} href={href(item.id)} saved onSave={() => onToggle(item.id)} />
        </li>
      ))}
    </ul>
  );
}
