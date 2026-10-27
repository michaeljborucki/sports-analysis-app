"use client";

import { useMemo, useState } from "react";

import { SearchBox, TeamLogo } from "@/components/cfb/cfb-bits";
import { SourceChip } from "@/components/nba/nba-game-card";
import { Panel } from "@/components/ui";
import { fmtEff, fmtPts, type NbaTeamRow } from "@/lib/nba";

type SortKey =
  | "name"
  | "games"
  | "pace"
  | "off_eff"
  | "def_eff"
  | "points_for_per_game"
  | "points_against_per_game";

const COLUMNS: { key: SortKey; label: string; title: string; fmt: (t: NbaTeamRow) => string }[] = [
  { key: "games", label: "G", title: "Games in the sample", fmt: t => String(t.games) },
  { key: "pace", label: "Pace", title: "Possessions per game (FGA − OREB + TOV + 0.44 × FTA)", fmt: t => fmtPts(t.pace) },
  { key: "off_eff", label: "Off eff", title: "Points ÷ own possessions", fmt: t => fmtEff(t.off_eff) },
  { key: "def_eff", label: "Def eff", title: "Points allowed ÷ opponent possessions (lower is better)", fmt: t => fmtEff(t.def_eff) },
  { key: "points_for_per_game", label: "PF/g", title: "Points scored per game", fmt: t => fmtPts(t.points_for_per_game) },
  { key: "points_against_per_game", label: "PA/g", title: "Points allowed per game", fmt: t => fmtPts(t.points_against_per_game) },
];

export function NbaTeamsTable({ teams, minGames }: { teams: NbaTeamRow[]; minGames: number }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "off_eff", desc: true });

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = needle
      ? teams.filter(t =>
          [t.name, t.short_name, t.abbreviation].some(n => n?.toLowerCase().includes(needle)),
        )
      : teams;
    const dir = sort.desc ? -1 : 1;
    return [...rows].sort((a, b) => {
      if (sort.key === "name") return a.name.localeCompare(b.name) * dir;
      const av = a[sort.key] ?? -Infinity;
      const bv = b[sort.key] ?? -Infinity;
      return av === bv ? a.name.localeCompare(b.name) : (av < bv ? -1 : 1) * dir;
    });
  }, [teams, q, sort]);

  const toggle = (key: SortKey) =>
    setSort(s => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "name" && key !== "def_eff" }));
  const arrow = (key: SortKey) => (sort.key === key ? (sort.desc ? " ↓" : " ↑") : "");

  return (
    <Panel
      title={
        <>
          Teams <span className="tabular text-text-3">{shown.length}</span>
        </>
      }
      actions={<SearchBox value={q} onChange={setQ} />}
      bodyClassName="overflow-x-auto"
    >
      <table className="w-full border-collapse">
        <thead className="dt-head">
          <tr>
            <th className="dt-th w-10 text-right">#</th>
            <th className="dt-th">
              <button type="button" onClick={() => toggle("name")} className="hover:text-text-1">
                Team{arrow("name")}
              </button>
            </th>
            {COLUMNS.map(c => (
              <th key={c.key} className="dt-th text-right" title={c.title} aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : undefined}>
                <button type="button" onClick={() => toggle(c.key)} className="hover:text-text-1">
                  {c.label}
                  {arrow(c.key)}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((t, i) => (
            <tr key={t.team_id} className="dt-row">
              <td className="dt-td text-right tabular text-text-3">{i + 1}</td>
              <td className="dt-td">
                <div className="flex min-w-[12rem] items-center gap-2">
                  <TeamLogo side={t} />
                  <span className="truncate text-text-1">{t.name}</span>
                  <SourceChip side={t} minGames={minGames} />
                </div>
              </td>
              {COLUMNS.map(c => (
                <td key={c.key} className="dt-td text-right tabular text-text-2">
                  {c.fmt(t)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
