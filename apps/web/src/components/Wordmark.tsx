import { navigate } from "../lib/router";

/** "ReadLayer" set in the reading face; the dotted rule is the product's one visual idea. */
export function Wordmark({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <a
      className={`wordmark wordmark--${size}`}
      href="/"
      aria-label="ReadLayer home"
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate("/");
      }}
    >
      <span className="wordmark__read">Read</span>
      <span className="wordmark__layer">Layer</span>
    </a>
  );
}
