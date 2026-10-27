"use client";

import { Suspense, use } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import clsx from "clsx";

import { TeamLogo } from "@/components/cfb/cfb-bits";
import { KICKOFF } from "@/components/cfb/cfb-game-card";
import { RefreshButton } from "@/components/refresh-button";
import { Chip, ErrorBanner, PageHeader, Panel } from "@/components/ui";
import { apiPaths } from "@/lib/api";
import {
  LEAN_MIN,
  cfbGameHref,
  SMALL_SAMPLE_GAMES,
  fmtPpp,
  fmtPts,
  fmtSpread,
  gameLeans,
  teamLabel,
  type CfbGame,
  type CfbPredictionsResponse,
  type CfbSide,
  type CfbTeamRow,
} from "@/lib/cfb";

export default function CfbGamePage({ params }: { params: Promise<{ eventId: string }> }) {
  const { eventId } = use(params);
  return (
    <Suspense fallback={<Loading />}>
      <CfbGameInner eventId={decodeURIComponent(eventId)} />
    </Suspense>
  );
}

function CfbGameInner({ eventId }: { eventId: string }) {
  const searchParams = useSearchParams();
  const weekParam = Number(searchParams.get("week"));
  const week = Number.isInteger(weekParam) && weekParam >= 1 ? weekParam : undefined;

  const { data, error, isLoading, isValidating, mutate } = useSWR<CfbPredictionsResponse>(
    apiPaths.cfbPredictions(week),
    { refreshInterval: 300_000 },
  );
  const game = data?.games.find(g => g.event_id === eventId);
  const teams = new Map((data?.teams ?? []).map(t => [t.team_id, t]));
  const backWeek = data?.week ?? week;
  const backHref = `/cfb${backWeek && backWeek !== data?.current_week ? `?week=${backWeek}` : ""}`;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link href={backHref} className="text-[length:var(--fs-13)] text-text-2 hover:text-text-1">
          ‹ All week {backWeek ?? "…"} games
        </Link>
        {data && game && <GameNav games={data.games} current={game} week={data.week} />}
      </div>
      <PageHeader
        className="mb-0"
        title={game ? `${game.away.name} @ ${game.home.name}` : "Game breakdown"}
        description={
          game ? (
            <>
              <span className="tabular">{KICKOFF.format(new Date(game.commence_time))}</span>
              {game.division === "fcs" && " · FCS"}
              {game.neutral_site && " · Neutral site"}
              {game.completed && " · Final"}
              {data && (
                <>
                  {" "}· rates from <span className="tabular">{data.games_used}</span> games before week{" "}
                  <span className="tabular">{data.week}</span>
                </>
              )}
            </>
          ) : undefined
        }
        actions={<RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />}
      />

      {error && (
        <ErrorBanner
          tone="loss"
          title="College football projections are unavailable (ESPN or the API server)."
          details={String(error)}
        />
      )}
      {isLoading && !data && <Loading />}
      {data && !game && (
        <div className="rounded-lg border border-border-subtle bg-bg-1 py-10 text-center text-text-3">
          This game isn&apos;t on the week {data.week} slate.
        </div>
      )}
      {game && (
        <>
          <Scoreboard game={game} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Derivation side={game.away} opp={game.home} />
            <Derivation side={game.home} opp={game.away} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SeasonStats game={game} teams={teams} />
            <MarketPanel game={game} />
          </div>
        </>
      )}
    </div>
  );
}

/** Step through the week's games without going back to the list. */
function GameNav({ games: all, current, week }: { games: CfbGame[]; current: CfbGame; week: number }) {
  const router = useRouter();
  // Step within the game's own division (FBS slate or FCS slate).
  const games = all.filter(g => g.division === current.division);
  const i = games.findIndex(g => g.event_id === current.event_id);
  const prev = i > 0 ? games[i - 1] : null;
  const next = i < games.length - 1 ? games[i + 1] : null;
  const btn =
    "inline-flex h-7 items-center rounded border border-border-subtle px-2 text-[length:var(--fs-13)] text-text-2 transition-colors hover:text-text-1";
  return (
    <div className="ml-auto flex items-center gap-1.5">
      {prev ? (
        <Link href={cfbGameHref(prev, week)} className={btn} title={`${prev.away.name} @ ${prev.home.name}`}>
          ‹ Prev
        </Link>
      ) : (
        <span className={clsx(btn, "opacity-40")}>‹ Prev</span>
      )}
      <select
        aria-label="Jump to game"
        value={current.event_id}
        onChange={e => {
          const g = games.find(x => x.event_id === e.target.value);
          if (g) router.push(cfbGameHref(g, week));
        }}
        className="h-7 max-w-[18rem] rounded border border-border-subtle bg-bg-0 px-2 text-[length:var(--fs-13)] text-text-1"
      >
        {games.map((g, n) => (
          <option key={g.event_id} value={g.event_id}>
            {n + 1}. {teamLabel(g.away)} @ {teamLabel(g.home)}
          </option>
        ))}
      </select>
      <span className="tabular text-[length:var(--fs-12)] text-text-3">
        {i + 1}/{games.length}
      </span>
      {next ? (
        <Link href={cfbGameHref(next, week)} className={btn} title={`${next.away.name} @ ${next.home.name}`}>
          Next ›
        </Link>
      ) : (
        <span className={clsx(btn, "opacity-40")}>Next ›</span>
      )}
    </div>
  );
}

function Scoreboard({ game: g }: { game: CfbGame }) {
  return (
    <section className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 rounded-lg border border-border-subtle bg-bg-1 px-5 py-5">
      <ScoreSide side={g.away} opp={g.home} align="left" />
      <div className="text-center text-[length:var(--fs-12)] text-text-3">
        <div>projected</div>
        <div className="tabular text-text-2">total {fmtPts(g.predicted_total)}</div>
      </div>
      <ScoreSide side={g.home} opp={g.away} align="right" />
    </section>
  );
}

function ScoreSide({ side, opp, align }: { side: CfbSide; opp: CfbSide; align: "left" | "right" }) {
  const won =
    side.actual_points != null && opp.actual_points != null && side.actual_points > opp.actual_points;
  return (
    <div className={clsx("flex min-w-0 items-center gap-3", align === "right" && "flex-row-reverse text-right")}>
      <TeamLogo side={side} size={44} />
      <div className="min-w-0">
        <div className="truncate text-[length:var(--fs-15)] font-medium text-text-1" title={side.name}>
          {align === "right" && <span className="mr-1 text-text-3">@</span>}
          {side.name}
        </div>
        <div className="tabular text-[length:var(--fs-28)] font-semibold leading-tight text-text-1">
          {fmtPts(side.predicted_points)}
        </div>
        {side.actual_points != null && (
          <div className={clsx("tabular text-[length:var(--fs-13)]", won ? "text-text-1" : "text-text-3")}>
            final {side.actual_points}
          </div>
        )}
      </div>
    </div>
  );
}

/** The formula, step by step, for one team. */
function Derivation({ side, opp }: { side: CfbSide; opp: CfbSide }) {
  const steps: { label: string; detail: string; value: string; strong?: boolean }[] = [
    {
      label: "Plays per game",
      detail: `pass + rush attempts, ${side.games} game${side.games === 1 ? "" : "s"}`,
      value: fmtPts(side.plays_per_game),
    },
    {
      label: `${teamLabel(side)} offensive PPP`,
      detail: "points ÷ own plays",
      value: fmtPpp(side.off_ppp),
    },
    {
      label: "Offensive estimate",
      detail: `${fmtPts(side.plays_per_game)} × ${fmtPpp(side.off_ppp)}`,
      value: fmtPts(side.off_estimate),
    },
    {
      label: `${teamLabel(opp)} defensive PPP`,
      detail: `points allowed ÷ plays faced, ${opp.games} game${opp.games === 1 ? "" : "s"}`,
      value: fmtPpp(opp.def_ppp),
    },
    {
      label: "Defensive estimate",
      detail: `${fmtPts(side.plays_per_game)} × ${fmtPpp(opp.def_ppp)}`,
      value: fmtPts(side.def_estimate),
    },
    {
      label: "Projected points",
      detail: `(${fmtPts(side.off_estimate)} + ${fmtPts(side.def_estimate)}) ÷ 2`,
      value: fmtPts(side.predicted_points),
      strong: true,
    },
  ];
  const small = side.games < SMALL_SAMPLE_GAMES || opp.games < SMALL_SAMPLE_GAMES;

  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <TeamLogo side={side} />
          {side.name}
        </span>
      }
      actions={
        small && (
          <Chip tone="stale" title="Under 3 games for this team or its opponent">
            small sample
          </Chip>
        )
      }
    >
      <table className="w-full border-collapse">
        <tbody>
          {steps.map(s => (
            <tr key={s.label} className={clsx("dt-row", s.strong && "bg-bg-2")}>
              <td className="dt-td">
                <div className={s.strong ? "font-semibold text-text-1" : "text-text-1"}>{s.label}</div>
                <div className="tabular text-[length:var(--fs-12)] text-text-3">{s.detail}</div>
              </td>
              <td
                className={clsx(
                  "dt-td text-right tabular",
                  s.strong ? "text-[length:var(--fs-20)] font-semibold text-text-1" : "text-text-2",
                )}
              >
                {s.value}
              </td>
            </tr>
          ))}
          {side.actual_points != null && (
            <tr className="dt-row">
              <td className="dt-td text-text-2">Final score</td>
              <td className="dt-td text-right tabular text-text-1">
                {side.actual_points}
                {side.predicted_points != null && (
                  <span className="ml-2 text-[length:var(--fs-12)] text-text-3">
                    ({side.actual_points - side.predicted_points > 0 ? "+" : ""}
                    {(side.actual_points - side.predicted_points).toFixed(1)})
                  </span>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

const STAT_ROWS: { label: string; fmt: (t: CfbTeamRow | undefined, s: CfbSide) => string }[] = [
  { label: "Games", fmt: (_t, s) => String(s.games) },
  { label: "Plays / game", fmt: (_t, s) => fmtPts(s.plays_per_game) },
  { label: "Offensive PPP", fmt: (_t, s) => fmtPpp(s.off_ppp) },
  { label: "Defensive PPP", fmt: (_t, s) => fmtPpp(s.def_ppp) },
  { label: "Points for / game", fmt: t => fmtPts(t?.points_for_per_game) },
  { label: "Points against / game", fmt: t => fmtPts(t?.points_against_per_game) },
];

function SeasonStats({ game: g, teams }: { game: CfbGame; teams: Map<string, CfbTeamRow> }) {
  const away = teams.get(g.away.team_id);
  const home = teams.get(g.home.team_id);
  return (
    <Panel title="Season to date">
      <table className="w-full border-collapse">
        <thead className="dt-head">
          <tr>
            <th className="dt-th" />
            <th className="dt-th text-right">{teamLabel(g.away)}</th>
            <th className="dt-th text-right">{teamLabel(g.home)}</th>
          </tr>
        </thead>
        <tbody>
          {STAT_ROWS.map(r => (
            <tr key={r.label} className="dt-row">
              <td className="dt-td text-text-2">{r.label}</td>
              <td className="dt-td text-right tabular text-text-1">{r.fmt(away, g.away)}</td>
              <td className="dt-td text-right tabular text-text-1">{r.fmt(home, g.home)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function MarketPanel({ game: g }: { game: CfbGame }) {
  const leans = gameLeans(g);
  const rows = [
    {
      label: "Total",
      model: fmtPts(g.predicted_total),
      market: fmtPts(g.market_total),
      lean:
        leans.total != null && Math.abs(leans.total) >= LEAN_MIN
          ? `${leans.total > 0 ? "Over" : "Under"} ${Math.abs(leans.total).toFixed(1)}`
          : null,
    },
    {
      label: "Spread",
      model: fmtSpread(g.predicted_spread_home, g.home, g.away),
      market: fmtSpread(g.market_spread_home, g.home, g.away),
      lean:
        leans.spread != null && leans.spreadTeam && leans.spread >= LEAN_MIN
          ? `${teamLabel(leans.spreadTeam)} ${leans.spread.toFixed(1)}`
          : null,
    },
  ];
  return (
    <Panel title="Model vs market">
      <table className="w-full border-collapse">
        <thead className="dt-head">
          <tr>
            <th className="dt-th" />
            <th className="dt-th text-right">Model</th>
            <th className="dt-th text-right">Market</th>
            <th className="dt-th text-right">Lean</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.label} className="dt-row">
              <td className="dt-td text-text-2">{r.label}</td>
              <td className="dt-td whitespace-nowrap text-right tabular text-text-1">{r.model}</td>
              <td className="dt-td whitespace-nowrap text-right tabular text-text-2">{r.market}</td>
              <td className="dt-td text-right">
                {r.lean ? <Chip tone="edge">{r.lean}</Chip> : <span className="text-text-3">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-border-subtle px-4 py-2.5 text-[length:var(--fs-12)] text-text-3">
        Market = most-quoted line across books. Leans under {LEAN_MIN} pts are hidden; no home-field or
        strength-of-schedule adjustment.
      </p>
    </Panel>
  );
}

function Loading() {
  return (
    <div aria-label="Loading game breakdown" className="grid gap-4">
      <div className="skeleton h-28 rounded-lg" />
      <div className="skeleton h-80 rounded-lg" />
    </div>
  );
}
