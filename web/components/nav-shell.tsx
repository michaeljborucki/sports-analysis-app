"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { FetcherToggle } from "./fetcher-toggle";
import { SportSwitcher } from "./sport-switcher";
import { isSportKey } from "@/lib/sports";

// Per-sport sections — routed as /<section>/<sport>
const sportSections = [
  { key: "odds", label: "Odds" },
  { key: "props", label: "Props" },
  { key: "picks", label: "Picks" },
] as const;

// Global sections — routed as /<section> (no sport in URL)
const globalSections = [{ key: "arbitrage", label: "Arbitrage" }] as const;

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  // Current sport sticks as the user navigates sections
  const parts = pathname.split("/").filter(Boolean);
  const section = parts[0] ?? "odds";
  const sport = isSportKey(parts[1] ?? "") ? parts[1] : "mlb";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border-subtle bg-bg-1">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="text-sm font-semibold tracking-wide">
            <span className="text-accent">◆</span>{" "}
            <span className="text-text-1">betting site</span>
          </div>
          <SportSwitcher />
          <nav className="flex gap-5 text-sm">
            {sportSections.map(s => {
              const active = section === s.key;
              return (
                <Link
                  key={s.key}
                  href={`/${s.key}/${sport}`}
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
            <span className="text-text-3/40">·</span>
            {globalSections.map(s => {
              const active = section === s.key;
              return (
                <Link
                  key={s.key}
                  href={`/${s.key}`}
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
            <FetcherToggle />
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-4">
        {children}
      </main>
    </div>
  );
}
