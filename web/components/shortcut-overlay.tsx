"use client";
/**
 * Keyboard shortcuts overlay.
 *
 * Sibling of `command-palette.tsx` — both are discovery surfaces docked at
 * `top: 20vh`, sharing the same visual language (bg-bg-1/95, backdrop
 * blur, rounded-lg, shadow-2xl, border-border-subtle). Renders into a
 * portal on `document.body`, guarded by a mounted check.
 *
 * Open-state, the global `?` listener, and the custom-event bridge live
 * in `shortcut-overlay-mount.tsx`; this component is pure UI.
 *
 * Scroll-lock decision: matches command-palette — we do NOT lock body
 * scroll. The overlay is non-modal in spirit: it's a glance-and-dismiss
 * reference card, not a form.
 */
import * as React from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";
import { Keyboard as KeyboardIcon, X as CloseIcon } from "lucide-react";

import { useIsMounted } from "@/lib/use-is-mounted";
import {
  SHORTCUTS,
  SHORTCUT_GROUP_ORDER,
  remapKeysForPlatform,
  type ShortcutEntry,
  type ShortcutGroup,
} from "@/lib/shortcuts";

export interface ShortcutOverlayProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}

export function ShortcutOverlay({ open, onOpenChange }: ShortcutOverlayProps) {
  const mounted = useIsMounted();
  const close = React.useCallback(() => onOpenChange(false), [onOpenChange]);

  // Platform detection matches the nav-shell trigger's pattern: default
  // to Mac on SSR (safe default since ⌘ is the interesting case) and
  // downgrade to `Ctrl` on mount if the UA disagrees. Avoids hydration
  // mismatch — first paint always shows ⌘.
  const [isMac, setIsMac] = React.useState(true);
  React.useEffect(() => {
    if (typeof navigator === "undefined") return;
    const ua = navigator.userAgent || "";
    setIsMac(/Mac|iPhone|iPod|iPad/.test(ua));
  }, []);

  // Escape-to-close. Single listener, scoped to the open state.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Group rows for rendering. Preserves the module's declaration order
  // within each group.
  const grouped = React.useMemo(() => {
    const buckets = new Map<ShortcutGroup, ShortcutEntry[]>();
    for (const s of SHORTCUTS) {
      const arr = buckets.get(s.group) ?? [];
      arr.push(s);
      buckets.set(s.group, arr);
    }
    return buckets;
  }, []);

  if (!mounted || !open) return null;

  return createPortal(
    <div
      className={clsx(
        "fixed inset-0 z-[100]",
        "bg-black/40 backdrop-blur-[2px]",
        "flex items-start justify-center"
      )}
      style={{ paddingTop: "20vh" }}
      onClick={close}
      role="presentation"
    >
      <div
        className={clsx(
          "w-[640px] max-w-[calc(100vw-2rem)]",
          "bg-bg-1/95 backdrop-blur-md",
          "border border-border-subtle rounded-lg shadow-2xl",
          "overflow-hidden"
        )}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="Keyboard shortcuts"
        aria-modal="true"
      >
        {/* Header */}
        <div
          className={clsx(
            "flex items-center gap-2.5 px-4 h-12",
            "border-b border-border-subtle"
          )}
        >
          <KeyboardIcon
            size={16}
            className="text-text-3 shrink-0"
            aria-hidden
          />
          <h2
            className="flex-1 text-text-1 font-medium"
            style={{
              fontSize: "var(--fs-13)",
              lineHeight: "var(--lh-13)",
            }}
          >
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close"
            className={clsx(
              "shrink-0 inline-flex items-center justify-center",
              "w-6 h-6 rounded text-text-3",
              "hover:bg-bg-2 hover:text-text-1",
              "transition-colors"
            )}
          >
            <CloseIcon size={14} aria-hidden />
          </button>
        </div>

        {/* Body */}
        <div
          className={clsx(
            "max-h-[60vh] overflow-y-auto overflow-x-hidden",
            "px-1.5 py-1.5"
          )}
        >
          {SHORTCUT_GROUP_ORDER.map(group => {
            const rows = grouped.get(group);
            if (!rows || rows.length === 0) return null;
            return (
              <section key={group} className="mb-2 last:mb-0">
                <div
                  className={clsx(
                    "px-2 pt-3 pb-1.5",
                    "uppercase tracking-wider text-text-3 font-medium"
                  )}
                  style={{ fontSize: "10px", lineHeight: "12px" }}
                >
                  {group}
                </div>
                <div>
                  {rows.map((row, i) => (
                    <ShortcutRow
                      key={`${row.group}:${row.label}:${i}`}
                      entry={row}
                      isMac={isMac}
                      isLast={i === rows.length - 1}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>

        {/* Footer hint */}
        <div
          className={clsx(
            "flex items-center gap-4 px-4 h-8",
            "border-t border-border-subtle",
            "text-text-3"
          )}
          style={{ fontSize: "10px", lineHeight: "12px" }}
        >
          <FooterHint keyName="esc">to dismiss</FooterHint>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ─────────────────────────── Row ───────────────────────────

function ShortcutRow({
  entry,
  isMac,
  isLast,
}: {
  entry: ShortcutEntry;
  isMac: boolean;
  isLast: boolean;
}) {
  const mappedKeys = React.useMemo(
    () => remapKeysForPlatform(entry.keys, isMac),
    [entry.keys, isMac]
  );
  const dim = entry.running === false;

  return (
    <div
      className={clsx(
        "flex items-center gap-3 px-3 py-2 mx-1",
        !isLast && "border-b border-border-subtle/50",
        dim ? "text-text-3" : "text-text-2"
      )}
    >
      <span
        className="flex-1 truncate"
        style={{ fontSize: "var(--fs-13)", lineHeight: "var(--lh-13)" }}
      >
        {entry.label}
        {dim && (
          <span className="ml-2 text-text-3 text-[10px] uppercase tracking-wide">
            coming soon
          </span>
        )}
      </span>
      <KeyCombo keys={mappedKeys} />
    </div>
  );
}

// ─────────────────────── Key chip rendering ───────────────────────

/**
 * Render a sequence of key segments. A segment equal to `"then"` is
 * rendered as a small subscript separator for sequential chords (e.g.
 * `G then D`). All other segments are rendered as `<kbd>` chips with a
 * thin gap between them — no `+` separator (the visual grouping is
 * enough; `+` adds noise).
 */
function KeyCombo({ keys }: { keys: string[] }) {
  return (
    <span className="shrink-0 inline-flex items-center gap-1">
      {keys.map((k, i) => {
        if (k === "then") {
          return (
            <span
              key={`sep-${i}`}
              className="text-text-3 text-[9px] uppercase tracking-wide px-0.5"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              then
            </span>
          );
        }
        return <KeyChip key={`k-${i}-${k}`}>{k}</KeyChip>;
      })}
    </span>
  );
}

function KeyChip({ children }: { children: React.ReactNode }) {
  return (
    <kbd
      className={clsx(
        "inline-flex items-center justify-center",
        "h-5 min-w-[1.25rem] px-1.5 rounded-sm",
        "bg-bg-2 border border-border-subtle text-text-1"
      )}
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        lineHeight: "12px",
      }}
    >
      {children}
    </kbd>
  );
}

// ─────────────────────────── Chrome ───────────────────────────

function FooterHint({
  keyName,
  children,
}: {
  keyName: string;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-text-2" style={{ fontFamily: "var(--font-mono)" }}>
        {keyName}
      </span>
      <span>{children}</span>
    </span>
  );
}
