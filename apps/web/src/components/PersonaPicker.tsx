import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { PERSONAS, personaOf, type PersonaKey } from "../lib/personas";
import { Check, ChevronDown } from "./Icons";

interface PersonaPickerProps {
  value: PersonaKey;
  onChange: (key: PersonaKey) => void;
  /** Hide the name next to the avatar (tight phone layouts). */
  compact?: boolean;
}

/** Avatar chip that opens a listbox of demo readers. Arrow keys, Home/End, Enter, Escape. */
export function PersonaPicker({ value, onChange, compact = false }: PersonaPickerProps) {
  const [open, setOpen] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const current = personaOf(value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.focus();
  }, [open]);

  const show = () => {
    setFocusIndex(Math.max(0, PERSONAS.findIndex((p) => p.key === value)));
    setOpen(true);
  };
  const choose = (key: PersonaKey) => {
    onChange(key);
    setOpen(false);
    buttonRef.current?.focus();
  };

  const onButtonKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      show();
    }
  };

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const last = PERSONAS.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, focusIndex + 1),
      ArrowUp: Math.max(0, focusIndex - 1),
      Home: 0,
      End: last,
    };
    if (e.key in moves) {
      e.preventDefault();
      setFocusIndex(moves[e.key]!);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const p = PERSONAS[focusIndex];
      if (p) choose(p.key);
    } else if (e.key === "Escape" || e.key === "Tab") {
      if (e.key === "Escape") e.preventDefault();
      setOpen(false);
      if (e.key === "Escape") buttonRef.current?.focus();
    }
  };

  return (
    <div className="persona" ref={rootRef} data-persona={current.key}>
      <button
        ref={buttonRef}
        type="button"
        className={`persona__chip${compact ? " persona__chip--compact" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onButtonKey}
      >
        <Avatar persona={current.key} initials={current.initials} />
        <span className="persona__name">
          <span className="visually-hidden">Reading as </span>
          <span className="persona__name-full">{current.label}</span>
          <span className="persona__name-short" aria-hidden="true">
            {current.short}
          </span>
        </span>
        <ChevronDown size={14} className="persona__chevron" />
      </button>
      {open && (
        <ul
          ref={listRef}
          id={listId}
          className="persona__menu"
          role="listbox"
          tabIndex={-1}
          aria-label="Read as"
          aria-activedescendant={`${listId}-${focusIndex}`}
          onKeyDown={onListKey}
        >
          <li className="persona__menu-head eyebrow" role="presentation">
            Read as
          </li>
          {PERSONAS.map((p, i) => (
            <li
              key={p.key}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={p.key === value}
              data-focused={i === focusIndex}
              className="persona__option"
              onPointerEnter={() => setFocusIndex(i)}
              onClick={() => choose(p.key)}
            >
              <Avatar persona={p.key} initials={p.initials} />
              <span className="persona__option-text">
                <span className="persona__option-name">{p.label}</span>
                <span className="persona__option-blurb">{p.blurb}</span>
                <span className="persona__option-strengths">
                  Strong in {p.strengths.join(" · ")}
                </span>
              </span>
              {p.key === value && <Check size={16} className="persona__check" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Avatar({ persona, initials }: { persona: PersonaKey; initials: string }) {
  return (
    <span className="avatar" data-persona={persona} aria-hidden="true">
      {initials}
    </span>
  );
}
