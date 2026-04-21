"use client";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";

import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Right-docked persistent side sheet. Unlike a modal, this deliberately has
 * NO full-page scrim — the user can scroll and click the main grid with the
 * sheet open. Close paths:
 *   1. Top-right × button
 *   2. Escape key
 *   3. Click outside the sheet on an element NOT marked `data-sheet-keep-open`
 *      (so e.g. clicks on the nav shell close; clicks inside the odds table
 *      can swap content via their own row handler without closing first).
 *
 * The sheet portals into `document.body` so it escapes the `max-w-[1600px]`
 * page shell and sits flush to the viewport right edge. Before mount we
 * render nothing (SSR / hydration safety).
 *
 * Width clamps at `min(720px, 45vw)` so on narrow screens the sheet never
 * covers the first third of the odds grid.
 *
 * Body scroll is intentionally NOT locked — this is a persistent sheet, not
 * a modal; the user should still be able to scroll the grid underneath.
 */
export function SideSheet({
  open,
  onClose,
  header,
  children,
  ariaLabel,
}: {
  open: boolean;
  onClose: () => void;
  /** Sticky header row rendered at the top of the sheet. */
  header: ReactNode;
  children: ReactNode;
  ariaLabel?: string;
}) {
  const mounted = useIsMounted();

  // Escape-to-close. Only registered while open so we don't fight other
  // components that also listen for Escape.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Outside-click close. Document listener fires AFTER React synthetic
  // handlers, so row-click "swap content" handlers run first and update
  // state before we'd close. We bail if the click target is inside the
  // sheet itself OR any element tagged `data-sheet-keep-open` (the odds
  // table in our case).
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const target = e.target as Element | null;
      if (!target) return;
      if (target.closest("[data-side-sheet-root]")) return;
      if (target.closest("[data-sheet-keep-open]")) return;
      onClose();
    }
    // mousedown (not click) so we fire before a potential focus-steal
    // click on text selection inside the sheet.
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, onClose]);

  if (!mounted || !open) return null;

  return createPortal(
    <aside
      data-side-sheet-root
      role="complementary"
      aria-label={ariaLabel}
      className={clsx(
        "side-sheet-enter",
        // Fixed to the viewport right edge, full height below nothing (top:0)
        "fixed top-0 right-0 bottom-0 z-40",
        "flex flex-col",
        "bg-bg-2 border-l border-border-subtle",
        "shadow-[-8px_0_24px_rgba(0,0,0,0.45)]",
      )}
      style={{ width: "min(720px, 45vw)" }}
    >
      <header className="sticky top-0 z-10 bg-bg-2 border-b border-border-subtle px-4 py-3 flex items-start gap-3">
        <div className="flex-1 min-w-0">{header}</div>
        <button
          onClick={onClose}
          aria-label="Close side sheet"
          className={clsx(
            "shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-sm",
            "text-text-3 hover:text-text-1 hover:bg-bg-1 transition-colors",
          )}
          title="Close (Esc)"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            aria-hidden
          >
            <path
              d="M2 2L12 12M12 2L2 12"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </header>
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {children}
      </div>
    </aside>,
    document.body,
  );
}
