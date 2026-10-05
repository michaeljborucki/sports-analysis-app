"use client";
import Link from "next/link";
import clsx from "clsx";

import type { SportSummary } from "@/lib/api";

/**
 * Horizontal strip, one tile per configured sport, linking to its odds page.
 * Status is told in words and numbers, not colors: games today in text-1,
 * "N soon" in text-2, off-days dimmed.
 */
export function SportRail({ sports }: { sports: SportSummary[] }) {
  if (sports.length === 0) {
    return (
      <div className="rounded-lg border border-border-subtle bg-bg-1 px-4 py-3 text-[length:var(--fs-13)] text-text-3">
        No sports configured. Enable a sport in Settings.
      </div>
    );
  }

  return (
    <section aria-label="Sports">
      <h2 className="mb-2 text-[length:var(--fs-16)] leading-[var(--lh-16)] font-semibold text-text-1">
        Sports
      </h2>
      <div className="no-scrollbar overflow-x-auto">
        <div className="flex min-w-max gap-2">
          {sports.map(s => {
            const off = s.upcoming_games === 0 && s.starting_in_3h === 0;
            return (
              <Link
                key={s.key}
                href={`/odds/${s.key}`}
                className={clsx(
                  "flex w-[168px] shrink-0 flex-col gap-1 rounded-lg border border-border-subtle bg-bg-1 px-3 py-2.5",
                  "transition-colors hover:bg-bg-2",
                  off && "opacity-60",
                )}
              >
                <span className="text-[length:var(--fs-13)] font-semibold text-text-1">
                  {s.label}
                </span>
                <span className="flex items-baseline gap-3 text-[length:var(--fs-12)] text-text-3">
                  <span>
                    <span className="tabular font-semibold text-text-1">{s.upcoming_games}</span>{" "}
                    {s.upcoming_games === 1 ? "game" : "games"}
                  </span>
                  {s.starting_in_3h > 0 && (
                    <span className="ml-auto text-text-2">
                      <span className="tabular">{s.starting_in_3h}</span> soon
                    </span>
                  )}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}
