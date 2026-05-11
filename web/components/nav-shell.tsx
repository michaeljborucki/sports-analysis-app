"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import clsx from "clsx";

import { CacheModeToggle } from "./cache-mode-toggle";
import { LiveStatusFilter } from "./live-status-filter";
import { SportContextBar } from "./sport-context-bar";
import { SECTIONS, sectionByKey, sectionHref } from "@/lib/sections";
import { useCurrentSport } from "@/lib/use-current-sport";
import { useLiveFilter } from "@/lib/use-live-filter";

/**
 * Small chip in the header that signals "press ⌘K / Ctrl-K to open the
 * command palette" and doubles as a clickable trigger. Mac detection is
 * deferred to client-mount (via state) to avoid hydration mismatch —
 * server renders ⌘K as the safe default, client upgrades if applicable.
 */
function CommandPaletteTrigger() {
  const [isMac, setIsMac] = useState(true);
  useEffect(() => {
    if (typeof navigator === "undefined") return;
    // `navigator.platform` is deprecated but universally-supported and
    // enough for our discovery chip. Falling back to userAgent keeps this
    // correct on iPads (platform="MacIntel", touch).
    const ua = navigator.userAgent || "";
    setIsMac(/Mac|iPhone|iPod|iPad/.test(ua));
  }, []);

  const openPalette = () => {
    if (typeof window === "undefined") return;
    window.dispatchEvent(new CustomEvent("command-palette:open"));
  };

  return (
    <button
      type="button"
      onClick={openPalette}
      title="Open command palette"
      aria-label="Open command palette"
      className={clsx(
        "inline-flex items-center gap-1.5 h-7 px-2 rounded-md",
        "bg-bg-1 border border-border-subtle",
        "text-text-3 hover:text-text-1 hover:border-border-subtle",
        "transition-colors"
      )}
      style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}
    >
      <span aria-hidden>{isMac ? "⌘" : "Ctrl"}</span>
      <span aria-hidden>K</span>
    </button>
  );
}

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const firstSegment = pathname.split("/").filter(Boolean)[0];
  const activeSection = sectionByKey(firstSegment);
  const currentSport = useCurrentSport();
  const { value: liveFilter, setValue: setLiveFilter } = useLiveFilter();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border-subtle bg-bg-1">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="text-sm font-semibold tracking-wide">
            <span className="text-accent">◆</span>{" "}
            <span className="text-text-1">betting site</span>
          </div>
          <CommandPaletteTrigger />
          <nav className="flex gap-5 text-sm">
            {SECTIONS.map(s => {
              const active = s.key === activeSection?.key;
              return (
                <Link
                  key={s.key}
                  href={sectionHref(s, currentSport)}
                  className={clsx(
                    "py-1 transition-colors",
                    active
                      ? "text-text-1 border-b-2 border-accent"
                      : "text-text-2 hover:text-text-1"
                  )}
                >
                  {s.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <LiveStatusFilter value={liveFilter} onChange={setLiveFilter} />
            <CacheModeToggle />
          </div>
        </div>
      </header>
      {activeSection?.scope === "per-sport" && <SportContextBar />}
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-4">
        {children}
      </main>
    </div>
  );
}
