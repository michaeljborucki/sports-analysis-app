"use client";
/**
 * Cmd/Ctrl-K command palette.
 *
 * Renders a cmdk `<Command>` inside a portal docked near the top of the
 * viewport. The mount component (`command-palette-mount.tsx`) owns
 * open-state, installs the global keyboard listener, and builds the
 * `CommandContext` from the app-level hooks; this component is pure UI.
 *
 * Scroll-lock decision: we do NOT lock body scroll while the palette is
 * open. The palette is docked at top:20vh and the overlay behind it is
 * non-modal — the user can still see their page underneath and, worst
 * case, scroll with arrow keys or mouse wheel. Locking <body> with
 * overflow:hidden causes layout shift on every open/close due to
 * scrollbar width deltas, and measuring that width to apply padding is
 * fiddly. We choose zero-layout-shift over scroll-lock; open the palette
 * quickly, execute, close, move on.
 */
import * as React from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Command as CmdkCommand } from "cmdk";
import { Search as SearchIcon } from "lucide-react";
import clsx from "clsx";

import { useIsMounted } from "@/lib/use-is-mounted";
import { useLiveFilter } from "@/lib/use-live-filter";
import { useDensity } from "@/lib/use-density";
import {
  COMMANDS,
  GROUP_ICONS,
  type Command,
  type CommandContext,
  type CommandGroup,
} from "@/lib/commands";

const GROUP_ORDER: CommandGroup[] = ["Navigate", "Filter", "Action", "Search"];

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const mounted = useIsMounted();
  const router = useRouter();
  const { setValue: setLiveFilter } = useLiveFilter();
  const { setDensity } = useDensity();
  const [search, setSearch] = React.useState("");

  const close = React.useCallback(() => onOpenChange(false), [onOpenChange]);

  // Reset the search string whenever the palette closes so next-open starts
  // clean. Keeping stale input across sessions feels broken.
  React.useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  // Escape-to-close. cmdk's dialog component would handle this for us, but
  // we render inline (not via Radix Dialog) so we can control the visual
  // layout precisely. A single keydown listener is sufficient.
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

  // Group commands for cmdk's ordered rendering. Object key order follows
  // GROUP_ORDER so Navigate always comes first.
  const grouped = React.useMemo(() => {
    const buckets: Record<CommandGroup, Command[]> = {
      Navigate: [],
      Filter: [],
      Action: [],
      Search: [],
    };
    for (const c of COMMANDS) buckets[c.group].push(c);
    return buckets;
  }, []);

  const ctx: CommandContext = React.useMemo(
    () => ({
      router,
      setLiveFilter,
      setDensity,
      close,
    }),
    [router, setLiveFilter, setDensity, close]
  );

  if (!mounted || !open) return null;

  return createPortal(
    <div
      // Full-screen overlay. Click-outside closes; the card below stops
      // propagation so clicks inside don't bubble here.
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
        aria-label="Command palette"
        aria-modal="true"
      >
        <CmdkCommand
          label="Command palette"
          loop
          // command-score handles fuzzy matching out of the box.
          className="flex flex-col"
        >
          {/* Input row */}
          <div className="flex items-center gap-2.5 px-4 h-12 border-b border-border-subtle">
            <SearchIcon
              size={16}
              className="text-text-3 shrink-0"
              aria-hidden
            />
            <CmdkCommand.Input
              autoFocus
              value={search}
              onValueChange={setSearch}
              placeholder="Type a command or search…"
              className={clsx(
                "flex-1 bg-transparent outline-none border-0",
                "text-sm text-text-1 placeholder:text-text-3"
              )}
              style={{
                fontSize: "var(--fs-13)",
                lineHeight: "var(--lh-13)",
              }}
            />
            <KeyChip>ESC</KeyChip>
          </div>

          {/* Results list */}
          <CmdkCommand.List
            className={clsx(
              "max-h-[360px] overflow-y-auto overflow-x-hidden",
              "px-1.5 py-1.5"
            )}
          >
            <CmdkCommand.Empty
              className="px-3 py-6 text-center text-xs text-text-3"
            >
              No results. Try &ldquo;odds&rdquo;, &ldquo;picks&rdquo;, or
              &ldquo;density&rdquo;.
            </CmdkCommand.Empty>

            {GROUP_ORDER.map(group => {
              const items = grouped[group];
              if (!items || items.length === 0) return null;
              return (
                <CmdkCommand.Group
                  key={group}
                  heading={group}
                  className={clsx(
                    // cmdk stamps [cmdk-group-heading] on the <div> it
                    // generates for the heading; target it with the data
                    // attribute selector Tailwind v4 supports via [ ].
                    "[&_[cmdk-group-heading]]:px-2",
                    "[&_[cmdk-group-heading]]:pt-3",
                    "[&_[cmdk-group-heading]]:pb-1.5",
                    "[&_[cmdk-group-heading]]:uppercase",
                    "[&_[cmdk-group-heading]]:tracking-wider",
                    "[&_[cmdk-group-heading]]:text-text-3",
                    "[&_[cmdk-group-heading]]:font-medium",
                    "[&_[cmdk-group-heading]]:text-[10px]"
                  )}
                >
                  {items.map(cmd => (
                    <PaletteRow key={cmd.id} cmd={cmd} ctx={ctx} />
                  ))}
                </CmdkCommand.Group>
              );
            })}
          </CmdkCommand.List>

          {/* Footer hint bar */}
          <div
            className={clsx(
              "flex items-center gap-4 px-4 h-8",
              "border-t border-border-subtle",
              "text-text-3"
            )}
            style={{ fontSize: "10px", lineHeight: "12px" }}
          >
            <FooterHint keyName="↵">to select</FooterHint>
            <FooterHint keyName="↑↓">to navigate</FooterHint>
            <FooterHint keyName="esc">to dismiss</FooterHint>
          </div>
        </CmdkCommand>
      </div>
    </div>,
    document.body
  );
}

// ─────────────────────────── Row ───────────────────────────

function PaletteRow({ cmd, ctx }: { cmd: Command; ctx: CommandContext }) {
  const icon = cmd.icon ?? GROUP_ICONS[cmd.group];
  return (
    <CmdkCommand.Item
      value={cmd.id}
      keywords={[cmd.label, ...(cmd.keywords ?? [])]}
      onSelect={() => {
        void cmd.run(ctx);
      }}
      className={clsx(
        "group flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer",
        "border-l-2 border-l-transparent",
        "text-text-2",
        // cmdk sets data-selected="true" on the active row. Use it to drive
        // the selection highlight; Tailwind arbitrary selectors do the rest.
        "data-[selected=true]:bg-bg-2",
        "data-[selected=true]:text-text-1",
        "data-[selected=true]:border-l-accent",
        "transition-colors"
      )}
    >
      <span
        className={clsx(
          "shrink-0 inline-flex items-center justify-center",
          "w-5 h-5 text-text-3",
          "group-data-[selected=true]:text-text-1"
        )}
        aria-hidden
      >
        {icon}
      </span>
      <span
        className="flex-1 truncate"
        style={{ fontSize: "var(--fs-13)", lineHeight: "var(--lh-13)" }}
      >
        {cmd.label}
      </span>
      {cmd.hint && (
        <span
          className="shrink-0 text-text-3 text-[10px] tracking-wide uppercase"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {cmd.hint}
        </span>
      )}
    </CmdkCommand.Item>
  );
}

// ─────────────────────────── Chrome ───────────────────────────

function KeyChip({ children }: { children: React.ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center justify-center",
        "h-5 px-1.5 rounded",
        "bg-bg-2 border border-border-subtle",
        "text-[10px] tracking-wide uppercase text-text-3"
      )}
      style={{ fontFamily: "var(--font-mono)" }}
    >
      {children}
    </span>
  );
}

function FooterHint({
  keyName,
  children,
}: {
  keyName: string;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="text-text-2"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {keyName}
      </span>
      <span>{children}</span>
    </span>
  );
}
