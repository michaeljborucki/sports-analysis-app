"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";

import { SearchBox } from "@/components/cfb/cfb-bits";
import { TIPOFF } from "@/components/nba/nba-game-card";
import { Chip, Panel, Segmented } from "@/components/ui";
import {
  SGP_STATS,
  fmtAmerican,
  fmtPct,
  sgpQualifies,
  teamLabel,
  type NbaTeam,
  type SgpGame,
  type SgpPlayer,
  type SgpResponse,
} from "@/lib/nba";

type Filter = "qualifying" | "usage" | "all";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "qualifying", label: "Qualifying" },
  { value: "usage", label: "24%+ usage" },
  { value: "all", label: "All players" },
];

export function NbaSgp({ data }: { data: SgpResponse }) {
  const [filter, setFilter] = useState<Filter>("usage");
  const [q, setQ] = useState("");
  const c = data.criteria;

  const games = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return data.games.map(g => {
      const players = g.players
        .filter(p =>
          filter === "all" ? true : filter === "usage" ? p.pass_usage : sgpQualifies(p),
        )
        .filter(p => {
          if (!needle) return true;
          const team = p.team_id === g.home.team_id ? g.home : g.away;
          return [p.name, team.name, team.abbreviation].some(n => n?.toLowerCase().includes(needle));
        })
        // Qualifiers first, then by usage.
        .sort((a, b) => Number(sgpQualifies(b)) - Number(sgpQualifies(a)) || (b.usage ?? 0) - (a.usage ?? 0));
      return { ...g, players };
    });
  }, [data.games, filter, q]);

  const qualifying = data.games.reduce((n, g) => n + g.players.filter(sgpQualifies).length, 0);
  const shownCount = games.reduce((n, g) => n + g.players.length, 0);

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-4xl text-[length:var(--fs-13)] text-text-3">
        <span className="text-text-2">1.</span> Usage ≥ {c.usage_min}%.{" "}
        <span className="text-text-2">2.</span> Opponent in the bottom {c.dvp_bottom}{" "}vs the player&apos;s position
        (most fantasy points allowed per game to G / F / C; {c.fantasy_scoring}).{" "}
        <span className="text-text-2">3.</span> The highest points, rebounds and assists alt line each hit in ≥{" "}
        {Math.round(c.hit_min * 100)}% of games — this season once a player has {c.min_sample} games, last season
        before that. <span className="text-text-2">All 3</span>{" "}= share of games where every leg hit together (legs
        are correlated, so this beats multiplying). SGP prices aren&apos;t in any odds feed: the parlay has value only
        if the book&apos;s SGP price beats the break-even.
      </p>
      <p className="max-w-4xl rounded border border-[var(--stale-25)] bg-[var(--stale-10)] px-3 py-2 text-[length:var(--fs-13)] text-text-2">
        Backtest, 2025–26 (no look-ahead): <span className="tabular">209</span> qualifying parlays — the raw sample
        rate said <span className="tabular">90.6%</span>, they actually hit{" "}
        <span className="tabular text-text-1">81.3%</span>. The conservative estimate said{" "}
        <span className="tabular">82.2%</span>, so <span className="text-text-1">Beat</span> uses it; the raw price is
        shown below it. Raw 95–100% picks hit only <span className="tabular">75%</span> (n=
        <span className="tabular">36</span>).
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[length:var(--fs-14)] font-semibold text-text-1">
          Players <span className="tabular text-text-3">{shownCount}</span>
        </h2>
        <span className="text-[length:var(--fs-12)] text-text-3">
          <span className={clsx("tabular", qualifying > 0 ? "text-gain" : "text-text-2")}>{qualifying}</span> pass all
          three steps
        </span>
        <div className="ml-auto flex items-center gap-3">
          <Segmented<Filter> ariaLabel="SGP filter" size="sm" value={filter} onChange={setFilter} options={FILTERS} />
          <SearchBox value={q} onChange={setQ} />
        </div>
      </div>

      {data.games.length === 0 ? (
        <Empty>No games this day.</Empty>
      ) : shownCount === 0 ? (
        <Empty>
          {filter === "qualifying"
            ? "No player passes all three steps on this slate."
            : `No players${q ? ` matching “${q}”` : ""}.`}
        </Empty>
      ) : (
        games
          .filter(g => g.players.length > 0)
          .map(g => <GameTable key={g.event_id} game={g} data={data} />)
      )}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-1 py-10 text-center text-text-3">{children}</div>
  );
}

function GameTable({ game: g, data }: { game: SgpGame; data: SgpResponse }) {
  const teams = new Map<string, NbaTeam>([
    [g.home.team_id, g.home],
    [g.away.team_id, g.away],
  ]);
  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          {g.away.name} <span className="text-text-3">@</span> {g.home.name}
          <span className="tabular text-[length:var(--fs-12)] font-normal text-text-3">
            {TIPOFF.format(new Date(g.commence_time))}
            {g.completed && " · Final"}
          </span>
        </span>
      }
      bodyClassName="overflow-x-auto"
    >
      <table className="w-full min-w-[60rem] table-fixed border-collapse">
        <colgroup>
          <col />
          <col className="w-[5.5rem]" />
          <col className="w-[6.5rem]" />
          <col className="w-[6rem]" />
          <col className="w-[6rem]" />
          <col className="w-[6rem]" />
          <col className="w-[8rem]" />
          <col className="w-[7rem]" />
        </colgroup>
        <thead className="dt-head">
          <tr>
            <th className="dt-th">Player</th>
            <th className="dt-th text-right" title={`Usage rate over the sample; needs ≥ ${data.criteria.usage_min}%`}>
              Usage
            </th>
            <th
              className="dt-th text-right"
              title={`Opponent's rank in fantasy points allowed to this position (1 = allows the most); needs top ${data.criteria.dvp_bottom}`}
            >
              Matchup
            </th>
            {SGP_STATS.map(s => (
              <th
                key={s.key}
                className="dt-th text-right"
                title={`Highest ${s.label.toLowerCase()} alt line hit in ≥ ${Math.round(data.criteria.hit_min * 100)}% of games`}
              >
                {s.short}
              </th>
            ))}
            <th className="dt-th text-right" title="Games where all three legs hit together">
              All 3
            </th>
            <th
              className="dt-th text-right"
              title="Break-even American price: the book's SGP must pay better than this. Headline = conservative (90% lower bound on the joint hit rate); second line = raw sample rate"
            >
              Beat
            </th>
          </tr>
        </thead>
        <tbody>
          {g.players.map(p => (
            <PlayerRow key={p.athlete_id} p={p} team={teams.get(p.team_id)} opp={teams.get(p.opp_id)} data={data} />
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function PlayerRow({
  p,
  team,
  opp,
  data,
}: {
  p: SgpPlayer;
  team: NbaTeam | undefined;
  opp: NbaTeam | undefined;
  data: SgpResponse;
}) {
  const qualifies = sgpQualifies(p);
  const sampleNote =
    p.source === "last_season"
      ? `Last season, ${p.games} games (${p.current_games} this season — switches at ${data.criteria.min_sample})`
      : `This season, ${p.games} games`;
  return (
    <tr className={clsx("dt-row", qualifies && "bg-[var(--gain-10)]")}>
      <td className="dt-td">
        <div className="flex min-w-0 items-center gap-2.5">
          {p.headshot ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={p.headshot} alt="" className="h-8 w-8 shrink-0 rounded-full bg-bg-2 object-cover" loading="lazy" />
          ) : (
            <span className="h-8 w-8 shrink-0 rounded-full bg-bg-2" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-text-1">{p.name}</span>
              {qualifies && <Chip tone="gain">Qualifies</Chip>}
              {p.parlay_hit != null && (
                <Chip tone={p.parlay_hit ? "gain" : "loss"} title="Final: did all three legs hit?">
                  {p.parlay_hit ? "Hit" : "Miss"}
                </Chip>
              )}
              {p.injury && (
                <Chip tone="loss" title="ESPN roster injury status">
                  {p.injury}
                </Chip>
              )}
            </div>
            <div className="tabular text-[length:var(--fs-12)] text-text-3" title={sampleNote}>
              {p.position} · {team ? teamLabel(team) : ""} · {p.minutes.toFixed(1)} min · {p.games} g
              {p.source === "last_season" && <span className="text-stale"> · last season</span>}
            </div>
          </div>
        </div>
      </td>
      <td className={clsx("dt-td text-right tabular", p.pass_usage ? "text-gain" : "text-text-3")}>
        {p.usage == null ? "—" : `${p.usage.toFixed(1)}%`}
      </td>
      <td
        className={clsx("dt-td whitespace-nowrap text-right tabular", p.pass_matchup ? "text-gain" : "text-text-3")}
        title={
          p.opp_dvp != null
            ? `${opp ? teamLabel(opp) : "Opponent"} allows ${p.opp_dvp.toFixed(1)} fantasy pts/g to ${p.position}${
                p.opp_dvp_source === "last_season" ? " (last season)" : ""
              }`
            : undefined
        }
      >
        {opp ? teamLabel(opp) : "—"} #{p.opp_dvp_rank ?? "—"}
      </td>
      {SGP_STATS.map(s => {
        const leg = p.legs[s.key];
        return (
          <td
            key={s.key}
            className="dt-td whitespace-nowrap text-right tabular"
            title={leg ? `${leg.line}+ ${s.label.toLowerCase()}: ${leg.hits}/${leg.n} (${fmtPct(leg.rate)})` : "Lowest rung under the hit-rate bar"}
          >
            {leg ? (
              <>
                <span className="text-text-1">{leg.line}+</span>{" "}
                <span className="text-[length:var(--fs-12)] text-text-3">{fmtPct(leg.rate, 0)}</span>
              </>
            ) : (
              <span className="text-text-3">—</span>
            )}
            {p.actual && (
              <div
                className={clsx(
                  "text-[length:var(--fs-12)]",
                  !leg ? "text-text-3" : p.actual[s.key] >= leg.line ? "text-gain" : "text-loss",
                )}
                title="Final line"
              >
                had {p.actual[s.key]}
              </div>
            )}
          </td>
        );
      })}
      <td
        className="dt-td whitespace-nowrap text-right tabular"
        title={
          p.joint
            ? `All three hit ${p.joint.hits}/${p.joint.n}. Multiplied legs ${fmtPct(p.product)}; floor (1 − Σ misses) ${fmtPct(p.floor)}; conservative ${fmtPct(p.conservative)}`
            : undefined
        }
      >
        {p.joint ? (
          <>
            <span className="text-text-1">{fmtPct(p.joint.rate)}</span>{" "}
            <span className="text-[length:var(--fs-12)] text-text-3">
              {p.joint.hits}/{p.joint.n}
            </span>
          </>
        ) : (
          <span className="text-text-3">—</span>
        )}
      </td>
      <td className="dt-td whitespace-nowrap text-right tabular">
        {p.joint ? (
          <div className="flex flex-col items-end leading-tight">
            <span
              className="text-text-1"
              title={`Conservative: 90% lower bound on the joint hit rate (${fmtPct(p.conservative)}) — the backtest-calibrated number`}
            >
              {fmtAmerican(p.conservative_breakeven, p.conservative)}
            </span>
            <span
              className="text-[length:var(--fs-12)] text-text-3"
              title={`Raw: the sample's own joint hit rate (${fmtPct(p.joint.rate)}) — ran ~10 pts optimistic in the backtest`}
            >
              raw {fmtAmerican(p.breakeven, p.joint.rate)}
            </span>
          </div>
        ) : (
          <span className="text-text-3">—</span>
        )}
      </td>
    </tr>
  );
}
