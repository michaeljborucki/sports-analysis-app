"use client";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";

/**
 * One editable clause of the sentence filter: `before` is plain text, `value`
 * is the current setting rendered as a button; clicking it opens `control`
 * (rendered lazily — only the open clause's control is mounted).
 */
export interface SentenceClause {
  id: string;
  before?: ReactNode;
  value: ReactNode;
  after?: ReactNode;
  title?: string;
  /** The existing control for this filter, shown in the popover. */
  control: () => ReactNode;
  /** Popover heading, e.g. "Minimum edge". */
  heading?: string;
  /** Popover body padding. Lists (books, sports) render flush. */
  flush?: boolean;
}

/**
 * Sentence filter bar (spec §5, Edges): "Showing arbs in [all sports], edge
 * above [any], …". Each bracketed clause opens its control in a popover.
 */
export function FilterSentence({
  lead,
  clauses,
  aside,
}: {
  lead: ReactNode;
  clauses: SentenceClause[];
  aside?: ReactNode;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openId == null) return;
    const onDown = (e: MouseEvent) => {
      const root = rootRef.current;
      if (!root) return;
      const pop = root.querySelector("[data-sentence-popover]");
      const target = e.target as Node;
      if (pop?.contains(target)) return;
      // Clicks on another clause button are handled by its own onClick.
      if ((target as HTMLElement).closest?.("[data-sentence-clause]")) return;
      setOpenId(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenId(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openId]);

  return (
    <div
      ref={rootRef}
      className="flex flex-wrap items-baseline gap-x-6 gap-y-2 rounded-lg border border-border-subtle bg-bg-1 px-4 py-3"
    >
      <div className="min-w-0 flex-1 text-[length:var(--fs-14)] leading-[26px] text-text-2">
        {lead}
        {clauses.map((c, i) => {
          const open = openId === c.id;
          const last = i === clauses.length - 1;
          return (
            <Fragment key={c.id}>
              {" "}
              {c.before}
              {c.before ? " " : null}
              <span className="relative inline-block">
                <button
                  type="button"
                  data-sentence-clause
                  aria-expanded={open}
                  aria-haspopup="dialog"
                  title={c.title}
                  onClick={() => setOpenId(open ? null : c.id)}
                  className={clsx(
                    "rounded-sm px-0.5 font-medium text-text-1 underline decoration-dashed decoration-text-3 underline-offset-4 transition-colors hover:decoration-text-1",
                    open && "bg-bg-2 decoration-text-1",
                  )}
                >
                  {c.value}
                </button>
                {open && (
                  <span
                    data-sentence-popover
                    role="dialog"
                    aria-label={c.heading}
                    className="absolute left-0 top-full z-30 mt-2 block min-w-[220px] overflow-hidden rounded-lg border border-border-subtle bg-bg-1 text-left leading-normal shadow-[0_8px_24px_rgb(0_0_0/0.35)]"
                  >
                    {c.heading && (
                      <span className="block border-b border-border-subtle px-3 py-2 text-[length:var(--fs-12)] font-medium text-text-3">
                        {c.heading}
                      </span>
                    )}
                    <span className={clsx("block", !c.flush && "p-3")}>{c.control()}</span>
                  </span>
                )}
              </span>
              {c.after ? ` ${c.after}` : null}
              {last ? "." : ","}
            </Fragment>
          );
        })}
      </div>
      {aside && <div className="ml-auto shrink-0 text-[length:var(--fs-12)] text-text-3">{aside}</div>}
    </div>
  );
}

/** Number input styled for popovers. Behavior (clamping) is the caller's. */
export function PopoverNumberInput({
  value,
  onChange,
  min,
  max,
  step,
  prefix,
  suffix,
  placeholder,
  title,
  autoFocus = true,
}: {
  value: number;
  onChange: (raw: number) => void;
  min?: number;
  max?: number;
  step?: number;
  prefix?: string;
  suffix?: string;
  placeholder?: string;
  title?: string;
  autoFocus?: boolean;
}) {
  return (
    <span
      className="flex h-8 items-center gap-1 rounded-md border border-border-subtle bg-bg-2 px-2"
      title={title}
    >
      {prefix && <span className="tabular text-[length:var(--fs-13)] text-text-3">{prefix}</span>}
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="tabular w-full min-w-0 bg-transparent text-[length:var(--fs-13)] text-text-1 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      {suffix && <span className="tabular text-[length:var(--fs-13)] text-text-3">{suffix}</span>}
    </span>
  );
}

/** Vertical single-select list for popovers (sport picker). */
export function PopoverOptionList<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <span role="listbox" className="block max-h-[50vh] overflow-y-auto py-1">
      {options.map(o => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="option"
            aria-selected={on}
            onClick={() => onChange(o.value)}
            className={clsx(
              "block w-full px-3 py-1.5 text-left text-[length:var(--fs-13)] transition-colors",
              on ? "bg-bg-2 text-text-1" : "text-text-2 hover:bg-bg-2 hover:text-text-1",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </span>
  );
}
