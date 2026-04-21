"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

import { FetcherToggle } from "./fetcher-toggle";
import { LiveStatusFilter } from "./live-status-filter";
import { SportContextBar } from "./sport-context-bar";
import { SECTIONS, sectionByKey, sectionHref } from "@/lib/sections";
import { useCurrentSport } from "@/lib/use-current-sport";
import { useLiveFilter } from "@/lib/use-live-filter";

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
            <FetcherToggle />
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
