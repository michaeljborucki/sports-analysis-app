"use client";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import clsx from "clsx";

import type { SportSummary } from "@/lib/api";

/**
 * Horizontal chip strip — one chip per configured sport.
 *
 * Replaces the old vertical "SportStatusCards" list. Each chip shows sport
 * label, games today (starting-in-3h / total), picks-today count, and a
 * right-edge status dot that encodes activity:
 *
 *   green (price-up)  — games today
 *   amber (flash)     — games today, all live/late (upcoming_games == 0 but
 *                      starting_in_3h > 0 or a bet-card exists)
 *   gray  (text-3)    — off-day (no games, no picks, no card)
 *
 * Scrolls horizontally when the viewport is narrow. Uses the global
 * `.no-scrollbar` utility from globals.css and a right-edge mask so users
 * see the overflow cue.
 */
export function SportRail({ sports }: { sports: SportSummary[] }) {
  if (sports.length === 0) {
    return (
      <div className="rounded-md border border-border-subtle bg-bg-1 px-4 py-3 text-[11px] text-text-3">
        No sports configured. Enable a sport in Settings.
      </div>
    );
  }

  return (
    <div
      className="no-scrollbar overflow-x-auto"
      // Right-edge fade cue for scrollability. We only apply the mask when
      // content actually overflows; CSS mask handles it gracefully either way.
      style={{
        maskImage:
          "linear-gradient(to right, black 0%, black calc(100% - 24px), transparent 100%)",
        WebkitMaskImage:
          "linear-gradient(to right, black 0%, black calc(100% - 24px), transparent 100%)",
      }}
    >
      <div className="flex gap-2 min-w-max pr-6">
        {sports.map(s => {
          const hasGames = s.upcoming_games > 0;
          const startingSoon = s.starting_in_3h > 0;
          const hasCard = !!s.bet_card_date;
          // Status: off-day (nothing at all) → gray; all-live/late → amber;
          // otherwise green (active day).
          let dotClass = "bg-text-3";
          let dotTitle = "Off-day";
          if (hasGames) {
            dotClass = "bg-price-up";
            dotTitle = "Games today";
          } else if (startingSoon || hasCard) {
            dotClass = "bg-flash";
            dotTitle = "Games late or live-only";
          }

          return (
            <Link
              key={s.key}
              href={`/odds/${s.key}`}
              className={clsx(
                "group relative flex-shrink-0 w-[200px] rounded-md border border-border-subtle bg-bg-1",
                "px-3 py-2.5 flex flex-col gap-1.5",
                "hover:border-accent/50 hover:bg-bg-2 transition-colors",
              )}
              title={dotTitle}
            >
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold tracking-wide text-text-1 group-hover:text-accent">
                  {s.label}
                </span>
                <span
                  className={clsx(
                    "inline-block w-1.5 h-1.5 rounded-full",
                    dotClass,
                  )}
                  aria-label={dotTitle}
                />
              </div>

              <div className="flex items-baseline gap-3 text-[10px] uppercase tracking-wider text-text-3">
                <span className="inline-flex items-baseline gap-1">
                  <span className="tabular text-[13px] font-semibold text-text-1 tracking-normal">
                    {s.upcoming_games}
                  </span>
                  games
                </span>
                <span className="inline-flex items-baseline gap-1">
                  <span
                    className={clsx(
                      "tabular text-[13px] font-semibold tracking-normal",
                      s.picks_today > 0 ? "text-accent" : "text-text-2",
                    )}
                  >
                    {s.picks_today}
                  </span>
                  picks
                </span>
                {startingSoon && (
                  <span className="ml-auto inline-flex items-baseline gap-1 text-flash">
                    <span className="tabular text-[11px] font-semibold">
                      {s.starting_in_3h}
                    </span>
                    soon
                  </span>
                )}
              </div>

              {/* Hover affordance — subtle arrow slides in. */}
              <ArrowRight
                size={11}
                className="absolute right-2 bottom-2 text-accent opacity-0 group-hover:opacity-70 transition-opacity"
                aria-hidden
              />
            </Link>
          );
        })}
      </div>
    </div>
  );
}
