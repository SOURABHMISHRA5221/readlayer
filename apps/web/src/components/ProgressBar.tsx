import { useEffect, useRef, type RefObject } from "react";

/** Thin reading-progress line; writes a transform directly, so scrolling never re-renders. */
export function ProgressBar({ target }: { target: RefObject<HTMLElement | null> }) {
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let frame = 0;
    const paint = () => {
      frame = 0;
      const el = target.current;
      if (!el || !bar.current) return;
      const rect = el.getBoundingClientRect();
      const span = rect.height - window.innerHeight * 0.6;
      const progress = span <= 0 ? 1 : Math.min(1, Math.max(0, -rect.top / span));
      bar.current.style.transform = `scaleX(${progress})`;
      bar.current.parentElement?.setAttribute("aria-valuenow", String(Math.round(progress * 100)));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(paint);
    };
    paint();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(frame);
    };
  }, [target]);
  return (
    <div className="progress" role="progressbar" aria-label="Reading progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={0}>
      <div className="progress__fill" ref={bar} />
    </div>
  );
}
