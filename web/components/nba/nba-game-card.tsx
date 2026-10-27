"use client";

import Link from "next/link";
import clsx from "clsx";

import { TeamLogo } from "@/components/cfb/cfb-bits";
import { Chip } from "@/components/ui";
import {
  LEAN_MIN,
  fmtEff,
  fmtPts,
  fmtSpread,
  gameLeans,
  nbaGameHref,
  sourceTitle,
  teamLabel,
  type NbaGame,
  type NbaSide,
  type NbaTeam,
} from "@/lib/nba";

export const TIPOFF = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const SEASON_TYPE_LABEL: Record<number, string> = { 1: "Preseason", 3: "Playoffs", 5: "Play-in" };

/** One game: both teams' projected scores, the math behind each, and the market. */
export function NbaGameCard({
  game: g,
  date,
  minGames,
}: {
  game: NbaGame;
  date: string;
  minGames: number;
}) {
  return (
    <Link
      href={nbaGameHref(g, date)}
      aria-label={`${g.away.name} at ${g.home.name} breakdown`}
      className="group flex flex-col rounded-lg border border-border-subtle bg-bg-1 transition-colors hover:border-text-3"
    >
      <header className="flex h-9 items-center gap-2 border-b border-border-subtle px-4 text-[length:var(--fs-12)] text-text-3">
        <span className="tabular">{TIPOFF.format(new Date(g.commence_time))}</span>
        {SEASON_TYPE_LABEL[g.season_type] && <Chip>{SEASON_TYPE_LABEL[g.season_type]}</Chip>}
        {g.neutral_site && <span>· Neutral</span>}
        {g.completed && <span className="text-text-2">· Final</span>}
        <span className="ml-auto text-text-2 transition-colors group-hover:text-text-1">
          Breakdown ›
        </span>
      </header>

      <div className="flex flex-col divide-y divide-border-subtle">
        <TeamBlock side={g.away} opp={g.home} at={false} minGames={minGames} />
        <TeamBlock side={g.home} opp={g.away} at minGames={minGames} />
      </div>

      <MarketFooter game={g} />
    </Link>
  );
}

export function SourceChip({ side, minGames }: { side: NbaTeam; minGames: number }) {
  if (side.source !== "last_season") return null;
  return (
    <Chip tone="stale" title={sourceTitle(side, minGames)}>
      last season
    </Chip>
  );
}

function TeamBlock({
  side,
  opp,
  at,
  minGames,
}: {
  side: NbaSide;
  opp: NbaSide;
  at: boolean;
  minGames: number;
}) {
  const won =
    side.actual_points != null && opp.actual_points != null && side.actual_points > opp.actual_points;
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2.5">
        <TeamLogo side={side} size={28} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[length:var(--fs-15)] font-medium text-text-1" title={side.name}>
              {at && <span className="mr-1 text-text-3">@</span>}
              {side.name}
            </span>
            <SourceChip side={side} minGames={minGames} />
            {side.games === 0 && <Chip tone="stale">no data</Chip>}
          </div>
        </div>
        <div className="flex items-baseline gap-2">
          {side.actual_points != null && (
            <span
              className={clsx("tabular text-[length:var(--fs-13)]", won ? "text-text-1" : "text-text-3")}
              title="Final score"
            >
              final {side.actual_points}
            </span>
          )}
          <span
            className="tabular text-[length:var(--fs-22)] font-semibold leading-none text-text-1"
            title="Projected points"
          >
            {fmtPts(side.predicted_points)}
          </span>
        </div>
      </div>
      <FormulaLine side={side} opp={opp} />
    </div>
  );
}

/** "98.3 poss × 1.168 off = 114.8 · × 1.066 DET def = 104.8 → avg 109.8" */
export function FormulaLine({ side, opp }: { side: NbaSide; opp: NbaSide }) {
  if (side.pace == null) {
    return <p className="mt-1.5 text-[length:var(--fs-12)] text-text-3">No box scores in the sample yet.</p>;
  }
  return (
    <p className="mt-1.5 flex flex-wrap gap-x-1.5 pl-[38px] text-[length:var(--fs-12)] text-text-3">
      <span className="tabular">
        <span className="text-text-2">{fmtPts(side.pace)}</span> poss
      </span>
      <span className="tabular">
        × {fmtEff(side.off_eff)} off = <span className="text-text-2">{fmtPts(side.off_estimate)}</span>
      </span>
      <span>·</span>
      <span className="tabular">
        × {fmtEff(opp.def_eff)} {teamLabel(opp)} def = <span className="text-text-2">{fmtPts(side.def_estimate)}</span>
      </span>
      <span>→</span>
      <span className="tabular">
        avg <span className="text-text-1">{fmtPts(side.predicted_points)}</span>
      </span>
    </p>
  );
}

function MarketFooter({ game: g }: { game: NbaGame }) {
  const leans = gameLeans(g);
  return (
    <div className="mt-auto grid grid-cols-2 gap-3 border-t border-border-subtle px-4 py-2.5 text-[length:var(--fs-12)]">
      <div>
        <div className="text-text-3">Total</div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="tabular text-text-1">{fmtPts(g.predicted_total)}</span>
          <span className="tabular text-text-3">mkt {fmtPts(g.market_total)}</span>
          {leans.total != null && Math.abs(leans.total) >= LEAN_MIN && (
            <Chip tone="edge" title="Model total minus market total">
              {leans.total > 0 ? "Over" : "Under"} {Math.abs(leans.total).toFixed(1)}
            </Chip>
          )}
        </div>
      </div>
      <div>
        <div className="text-text-3">Spread</div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="tabular whitespace-nowrap text-text-1">
            {fmtSpread(g.predicted_spread_home, g.home, g.away)}
          </span>
          <span className="tabular whitespace-nowrap text-text-3">
            mkt {fmtSpread(g.market_spread_home, g.home, g.away)}
          </span>
          {leans.spread != null && leans.spreadTeam && leans.spread >= LEAN_MIN && (
            <Chip
              tone="edge"
              title="Points of difference between the model spread and the market spread, toward this team"
            >
              {teamLabel(leans.spreadTeam)} {leans.spread.toFixed(1)}
            </Chip>
          )}
        </div>
      </div>
    </div>
  );
}
