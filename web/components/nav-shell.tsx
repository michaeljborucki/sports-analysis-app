"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  Crosshair,
  LayoutGrid,
  ListChecks,
  ReceiptText,
  Rows3,
  Search,
  Settings2,
  UserRound,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { CacheModeToggle } from "./cache-mode-toggle";
import { LiveStatusFilter } from "./live-status-filter";
import { SportSwitcher } from "./sport-switcher";
import { SECTIONS, sectionByKey, sectionHref } from "@/lib/sections";
import { useCurrentSport } from "@/lib/use-current-sport";
import { useLiveFilter } from "@/lib/use-live-filter";

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutGrid,
  odds: Rows3,
  props: UserRound,
  systems: ListChecks,
  edges: Crosshair,
  accounts: Wallet,
  bets: ReceiptText,
  settings: Settings2,
};

function openPalette() {
  window.dispatchEvent(new CustomEvent("command-palette:open"));
}

/** ⌘K trigger styled as a search field. Mac detection after mount. */
function SearchTrigger({ compact = false }: { compact?: boolean }) {
  const [isMac, setIsMac] = useState(true);
  useEffect(() => {
    setIsMac(/Mac|iPhone|iPod|iPad/.test(navigator.userAgent || ""));
  }, []);
  return (
    <button
      type="button"
      onClick={openPalette}
      title="Search and commands"
      aria-label="Open command palette"
      className={clsx(
        "flex items-center gap-2 rounded-md border border-border-subtle bg-bg-0 text-text-3 hover:text-text-1 transition-colors",
        compact ? "h-8 px-2.5" : "h-8 w-full px-2.5",
      )}
    >
      <Search size={13} aria-hidden />
      {!compact && <span className="flex-1 text-left text-[length:var(--fs-13)]">Search</span>}
      <kbd className="tabular text-[length:var(--fs-11)] text-text-3">{isMac ? "⌘K" : "Ctrl K"}</kbd>
    </button>
  );
}

/**
 * App shell (spec §3): a left rail at ≥1024px with sections, search, the
 * live/upcoming filter and the data-source control; a top bar below that.
 * Per-sport sections get the sport switcher above the page content.
 */
export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const firstSegment = pathname.split("/").filter(Boolean)[0];
  const activeSection = sectionByKey(firstSegment);
  const currentSport = useCurrentSport();
  const { value: liveFilter, setValue: setLiveFilter } = useLiveFilter();

  const links = SECTIONS.map(s => {
    const active = s.key === activeSection?.key;
    const Icon = ICONS[s.key];
    return { s, active, Icon };
  });

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[200px_minmax(0,1fr)]">
      {/* Rail (≥1024px) */}
      <aside className="hidden lg:flex sticky top-0 h-screen flex-col gap-1 border-r border-border-subtle bg-bg-1 px-3 py-4">
        <Link href="/dashboard" className="px-2.5 pb-3 text-[length:var(--fs-16)] font-bold tracking-[-0.02em] text-text-1">
          betting site
        </Link>
        <div className="pb-3">
          <SearchTrigger />
        </div>
        <nav className="flex flex-col gap-0.5" aria-label="Sections">
          {links.map(({ s, active, Icon }) => (
            <Link
              key={s.key}
              href={sectionHref(s, currentSport)}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[length:var(--fs-14)] transition-colors",
                active ? "bg-bg-2 font-medium text-text-1" : "text-text-2 hover:bg-bg-2/60 hover:text-text-1",
              )}
            >
              {Icon && <Icon size={15} aria-hidden strokeWidth={1.75} className={active ? "text-text-1" : "text-text-3"} />}
              {s.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-2 border-t border-border-subtle pt-3">
          <LiveStatusFilter value={liveFilter} onChange={setLiveFilter} />
          <CacheModeToggle />
        </div>
      </aside>

      {/* Top bar (<1024px) */}
      <header className="lg:hidden sticky top-0 z-30 border-b border-border-subtle bg-bg-1">
        <div className="flex items-center gap-3 px-4 h-12">
          <Link href="/dashboard" className="font-bold text-text-1">betting site</Link>
          <SearchTrigger compact />
          <div className="ml-auto flex items-center gap-2">
            <LiveStatusFilter value={liveFilter} onChange={setLiveFilter} />
          </div>
        </div>
        <nav className="no-scrollbar flex gap-1 overflow-x-auto px-3 pb-2" aria-label="Sections">
          {links.map(({ s, active }) => (
            <Link
              key={s.key}
              href={sectionHref(s, currentSport)}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "shrink-0 rounded-md px-2.5 py-1 text-[length:var(--fs-13)]",
                active ? "bg-bg-2 font-medium text-text-1" : "text-text-2",
              )}
            >
              {s.label}
            </Link>
          ))}
        </nav>
      </header>

      <main className="min-w-0 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
        <div className="mx-auto w-full max-w-[1680px]">
          {activeSection?.scope === "per-sport" && (
            <div className="mb-4">
              <SportSwitcher />
            </div>
          )}
          {children}
        </div>
      </main>
    </div>
  );
}
