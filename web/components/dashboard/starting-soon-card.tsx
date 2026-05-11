"use client";
import Link from "next/link";
import { CalendarOff, Clock } from "lucide-react";
import clsx from "clsx";

import type { Game } from "@/lib/api";
import { SPORTS, type SportKey } from "@/lib/sports";
import { EmptyState } from "@/components/empty-state";

/**
 * Next-5-games-in-3h module.
 *
 * Dense rows with a sport chip, away@home, and time-to-start. Clickable
 * — navigates to the sport's odds page. Deep-link to event page not yet
 * supported in the router, so we stop at /odds/{sport}.
 */
export function StartingSoonCard({
  games,
  onRefresh,
}: {
  games: Game[];
  onRefresh: () => void;
}) {
  const visible = games.slice(0, 5);

  return (
    <div className="rounded-md border border-border-subtle bg-bg-1 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-subtle">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-2">
          <Clock size={13} className="text-text-3" aria-hidden />
          Starting soon
        </div>
        <span className="text-[11px] text-text-3">next 3h</span>
      </div>
      {visible.length === 0 ? (
        <div className="p-4">
          <EmptyState
            icon={<CalendarOff size={28} />}
            title="Nothing starts in the next 3 hours"
            body="The upcoming-games window is scoped to the next 3 hours across all active sports. Check back closer to the next slate."
            action={{
              label: "Refresh",
              onClick: onRefresh,
              variant: "ghost",
            }}
          />
        </div>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {visible.map(g => (
            <li key={g.event_id}>
              <Link
                href={`/odds/${g.sport_key ?? "mlb"}`}
                className="flex items-center gap-3 px-4 py-2 hover:bg-bg-2/50 transition-colors"
                style={{
                  paddingTop: "var(--row-pad-y)",
                  paddingBottom: "var(--row-pad-y)",
                }}
              >
                <SportChip sport={g.sport_key ?? "mlb"} />
                <span className="flex-1 min-w-0 text-[12px] text-text-1 truncate">
                  {g.away_team} <span className="text-text-3">@</span>{" "}
                  {g.home_team}
                </span>
                <TimeBadge iso={g.commence_time} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SportChip({ sport }: { sport: string }) {
  const label = sport in SPORTS ? SPORTS[sport as SportKey].label : sport.toUpperCase();
  return (
    <span className="inline-flex items-center px-1.5 h-5 rounded-sm bg-bg-2 text-[10px] tracking-wider uppercase text-text-2 flex-shrink-0">
      {label}
    </span>
  );
}

function TimeBadge({ iso }: { iso: string }) {
  const d = new Date(iso);
  const diffMs = d.getTime() - Date.now();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-price-down tabular font-semibold flex-shrink-0">
        <span className="live-dot" />
        LIVE
      </span>
    );
  }
  const label =
    diffMin < 60
      ? `${diffMin}m`
      : diffMin < 24 * 60
        ? `${Math.round(diffMin / 60)}h`
        : d.toLocaleDateString([], { month: "short", day: "numeric" });
  const urgent = diffMin < 30;
  return (
    <span
      className={clsx(
        "text-[11px] tabular font-semibold flex-shrink-0",
        urgent ? "text-flash" : "text-accent",
      )}
    >
      {label}
    </span>
  );
}
