import { navigate } from "../lib/router";
import { Margo } from "./Margo";

/** The Gloss logo: Margo and a lowercase "gloss" in the UI face (DESIGN §19). */
export function Wordmark({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <a
      className={`wordmark wordmark--${size}`}
      href="/"
      aria-label="Gloss home"
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate("/");
      }}
    >
      <Margo size={size === "lg" ? 30 : 26} />
      <span className="wordmark__name">gloss</span>
    </a>
  );
}
