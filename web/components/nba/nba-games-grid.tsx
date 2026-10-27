"use client";

import { useMemo, useState } from "react";

import { SearchBox } from "@/components/cfb/cfb-bits";
import { NbaGameCard } from "@/components/nba/nba-game-card";
import type { NbaGame } from "@/lib/nba";

export function NbaGamesGrid({
  games,
  date,
  minGames,
}: {
  games: NbaGame[];
  date: string;
  minGames: number;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return games;
    return games.filter(g =>
      [g.home, g.away].some(t =>
        [t.name, t.short_name, t.abbreviation].some(n => n?.toLowerCase().includes(needle)),
      ),
    );
  }, [games, q]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <h2 className="text-[length:var(--fs-14)] font-semibold text-text-1">
          Games <span className="tabular text-text-3">{shown.length}</span>
        </h2>
        <div className="ml-auto">
          <SearchBox value={q} onChange={setQ} />
        </div>
      </div>
      {shown.length === 0 ? (
        <div className="rounded-lg border border-border-subtle bg-bg-1 py-10 text-center text-text-3">
          No games{q ? ` matching “${q}”` : " this day"}.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {shown.map(g => (
            <NbaGameCard key={g.event_id} game={g} date={date} minGames={minGames} />
          ))}
        </div>
      )}
    </div>
  );
}
