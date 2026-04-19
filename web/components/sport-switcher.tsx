"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import clsx from "clsx";

import { SPORTS, SPORT_ORDER, isSportKey, type SportKey } from "@/lib/sports";

/**
 * Sport dropdown in the nav. Reads the current sport from the URL segment
 * (the path looks like /odds/mlb → sport=mlb). Selecting a new sport keeps
 * the current section (odds/picks/props) and replaces the sport slug.
 */
export function SportSwitcher() {
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Parse /{section}/{sport} from the URL. If not on a sport-scoped page,
  // show the first sport as selected and navigate to /odds/{sport} on pick.
  const parts = pathname.split("/").filter(Boolean);
  const section = parts[0] && ["odds", "picks", "props"].includes(parts[0])
    ? parts[0]
    : "odds";
  const current: SportKey = isSportKey(parts[1] ?? "") ? (parts[1] as SportKey) : "mlb";

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  function pick(next: SportKey) {
    setOpen(false);
    router.push(`/${section}/${next}`);
  }

  const activeLabel = SPORTS[current].label;

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen(v => !v)}
        className={clsx(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
          "bg-bg-1 border border-border-subtle text-text-1",
          "hover:bg-bg-2 transition-colors"
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="text-text-3 text-[10px] uppercase tracking-wider">
          Sport
        </span>
        <span>{activeLabel}</span>
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path
            d="M4 6l4 4 4-4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && (
        <div
          role="listbox"
          className={clsx(
            "absolute top-full left-0 mt-2 z-20",
            "min-w-[160px]",
            "bg-bg-1 border border-border-subtle rounded-md shadow-2xl py-1"
          )}
        >
          {SPORT_ORDER.map(k => {
            const sp = SPORTS[k];
            const active = k === current;
            return (
              <button
                key={k}
                role="option"
                aria-selected={active}
                onClick={() => pick(k)}
                className={clsx(
                  "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left",
                  "transition-colors",
                  active
                    ? "bg-accent/15 text-accent"
                    : "text-text-2 hover:text-text-1 hover:bg-bg-2"
                )}
              >
                <span
                  aria-hidden
                  className={clsx(
                    "inline-block w-1.5 h-1.5 rounded-full",
                    active ? "bg-accent" : "bg-text-3/40"
                  )}
                />
                {sp.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
