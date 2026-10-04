import { useId, type KeyboardEvent } from "react";

interface Option<K extends string> {
  key: K;
  label: string;
}

interface SegmentedProps<K extends string> {
  label: string;
  options: readonly Option<K>[];
  value: K;
  onChange: (key: K) => void;
}

/** A radio group drawn as a segmented control; arrow keys move between options. */
export function Segmented<K extends string>({ label, options, value, onChange }: SegmentedProps<K>) {
  const labelId = useId();
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const i = options.findIndex((o) => o.key === value);
    const next = options[(i + step + options.length) % options.length];
    if (!next) return;
    onChange(next.key);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-key="${next.key}"]`)?.focus();
  };
  return (
    <div className="segmented">
      <span className="segmented__label" id={labelId}>
        {label}
      </span>
      <div className="segmented__track" role="radiogroup" aria-labelledby={labelId} onKeyDown={move}>
        {options.map((o) => {
          const checked = o.key === value;
          return (
            <button
              key={o.key}
              type="button"
              role="radio"
              data-key={o.key}
              aria-checked={checked}
              tabIndex={checked ? 0 : -1}
              className="segmented__option"
              onClick={() => onChange(o.key)}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
