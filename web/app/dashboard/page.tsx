"use client";
import Link from "next/link";
import useSWR from "swr";
import clsx from "clsx";

import { apiPaths, type DashboardResponse, type ArbOpportunity, type Pick, type Game, type SportSummary } from "@/lib/api";
import { formatAmerican, formatPct, formatUnits } from "@/lib/format";
import { BookLogo } from "@/components/book-logo";
import { RefreshButton } from "@/components/refresh-button";
import { SPORTS, type SportKey } from "@/lib/sports";

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

function roiColor(pct: number): string {
  if (pct >= 2) return "text-price-up";
  if (pct >= 1) return "text-accent";
  if (pct >= 0.5) return "text-flash";
  return "text-text-2";
}

function arbMarketLabel(op: ArbOpportunity): string {
  if (op.market_kind === "h2h") return "Moneyline";
  if (op.market_kind === "totals") return op.point != null ? `Total ${op.point}` : "Total";
  if (op.market_kind === "spreads") return op.point != null ? `Spread ±${op.point}` : "Spread";
  return op.market_kind;
}

function commenceLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffH = (d.getTime() - now.getTime()) / 3_600_000;
  if (diffH < 0) return "LIVE";
  if (diffH < 1) return `${Math.round(diffH * 60)}m`;
  if (diffH < 24) return `${Math.round(diffH)}h`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function MetricCard({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: "neutral" | "positive" | "warning";
}) {
  return (
    <div className="border border-border-subtle rounded-md bg-bg-1 px-4 py-3 flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-text-3">
        {label}
      </span>
      <span
        className={clsx(
          "text-2xl font-bold tabular",
          tone === "positive" && "text-price-up",
          tone === "warning" && "text-flash",
          tone === "neutral" && "text-text-1"
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[11px] text-text-3 tabular">{sub}</span>}
    </div>
  );
}

function MetricsStrip({ data }: { data: DashboardResponse }) {
  const totalGames = data.sports.reduce((sum, s) => sum + s.upcoming_games, 0);
  const totalPicks = data.sports.reduce((sum, s) => sum + s.picks_today, 0);
  const quotaRemaining = data.fetcher.requests_remaining;
  const quotaPct =
    quotaRemaining != null ? Math.round((quotaRemaining / 100_000) * 100) : null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
      <MetricCard
        label="Games Today"
        value={totalGames}
        sub={data.sports
          .map(s => `${s.label} ${s.upcoming_games}`)
          .join(" · ")}
      />
      <MetricCard
        label="Agent Picks"
        value={totalPicks}
        sub={data.sports
          .map(s => `${s.label} ${s.picks_today}`)
          .join(" · ")}
      />
      <MetricCard
        label="Arbs"
        value={data.top_arbs.length}
        sub={
          data.top_arbs[0]
            ? `top +${data.top_arbs[0].roi_pct.toFixed(2)}%`
            : "none detected"
        }
        tone={data.top_arbs.length > 0 ? "positive" : "neutral"}
      />
      <MetricCard
        label="Starting ≤ 3h"
        value={data.upcoming_games.length}
        sub={data.upcoming_games[0] ? commenceLabel(data.upcoming_games[0].commence_time) + " next" : "nothing soon"}
      />
      <MetricCard
        label="API Quota"
        value={quotaRemaining != null ? quotaRemaining.toLocaleString() : "—"}
        sub={quotaPct != null ? `${quotaPct}% remaining` : undefined}
        tone={quotaPct != null && quotaPct < 20 ? "warning" : "neutral"}
      />
    </div>
  );
}

function TopArbsCard({ arbs }: { arbs: ArbOpportunity[] }) {
  return (
    <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-bg-1 border-b border-border-subtle">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          Top arbs
        </span>
        <Link
          href="/arbitrage"
          className="text-[11px] text-accent hover:underline"
        >
          See all →
        </Link>
      </div>
      {arbs.length === 0 ? (
        <div className="text-center py-8 text-text-3 text-sm">
          No arbitrage opportunities right now.
        </div>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {arbs.map((op, i) => {
              const a = op.sides[0];
              const b = op.sides[1];
              return (
                <tr
                  key={`${op.event_id}-${i}`}
                  className="border-t border-border-subtle hover:bg-bg-1/40"
                >
                  <td className="px-3 py-2 w-[70px]">
                    <span className={clsx("tabular font-semibold", roiColor(op.roi_pct))}>
                      +{op.roi_pct.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-2 py-2 text-text-2 text-[11px] uppercase tracking-wide w-[60px]">
                    {sportLabel(op.sport_key)}
                  </td>
                  <td className="px-2 py-2 text-text-1 text-[11px] whitespace-nowrap">
                    {op.away_team} @ {op.home_team}
                  </td>
                  <td className="px-2 py-2 text-text-3 text-[11px]">
                    {arbMarketLabel(op)}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1.5">
                      <BookLogo bookKey={a.book} mode="label" />
                      <span className="text-text-3 text-[10px]">/</span>
                      <BookLogo bookKey={b.book} mode="label" />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StartingSoonCard({ games }: { games: Game[] }) {
  return (
    <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-bg-1 border-b border-border-subtle">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          Starting soon
        </span>
        <span className="text-[11px] text-text-3">next 3h</span>
      </div>
      {games.length === 0 ? (
        <div className="text-center py-8 text-text-3 text-sm">
          Nothing starts in the next 3 hours.
        </div>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {games.map(g => (
              <tr
                key={g.event_id}
                className="border-t border-border-subtle hover:bg-bg-1/40"
              >
                <td className="px-3 py-2 text-text-2 text-[11px] uppercase tracking-wide w-[60px]">
                  {sportLabel(g.sport_key ?? "mlb")}
                </td>
                <td className="px-2 py-2 text-text-1 whitespace-nowrap">
                  {g.away_team} @ {g.home_team}
                </td>
                <td className="px-2 py-2 text-right text-accent tabular text-[11px]">
                  {commenceLabel(g.commence_time)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TopPicksCard({ picks }: { picks: Pick[] }) {
  return (
    <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-bg-1 border-b border-border-subtle">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          Top picks by edge
        </span>
        <span className="text-[11px] text-text-3">cross-sport</span>
      </div>
      {picks.length === 0 ? (
        <div className="text-center py-8 text-text-3 text-sm">
          No picks from any agent today.
        </div>
      ) : (
        <table className="w-full text-xs">
          <thead className="bg-bg-1/40 text-text-2">
            <tr>
              <th className="text-left px-3 py-1.5 font-medium uppercase tracking-wide text-[10px] w-[50px]">Sport</th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">Game</th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">Pick</th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px] w-[55px]">Odds</th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px] w-[60px]">Edge</th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px] w-[55px]">Stake</th>
            </tr>
          </thead>
          <tbody>
            {picks.map(p => (
              <tr
                key={p.id}
                className="border-t border-border-subtle hover:bg-bg-1/40"
              >
                <td className="px-3 py-1.5 text-text-2 text-[11px] uppercase tracking-wide">
                  {sportLabel(p.sport_key ?? "mlb")}
                </td>
                <td className="px-2 py-1.5 text-text-1">{p.game_label}</td>
                <td className="px-2 py-1.5 text-text-2">{p.market_label}</td>
                <td className="px-2 py-1.5 text-right tabular">
                  {formatAmerican(p.odds_american)}
                </td>
                <td className="px-2 py-1.5 text-right tabular font-semibold text-price-up">
                  {formatPct(p.edge_pct, true)}
                </td>
                <td className="px-2 py-1.5 text-right tabular text-accent font-semibold">
                  {formatUnits(p.stake_units)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SportStatusCards({ sports }: { sports: SportSummary[] }) {
  return (
    <div className="flex flex-col gap-2">
      {sports.map(s => (
        <Link
          key={s.key}
          href={`/odds/${s.key}`}
          className="group border border-border-subtle rounded-md bg-bg-1 px-4 py-3 hover:border-accent/50 transition-colors"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-text-1 group-hover:text-accent">
              {s.label}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-text-3 group-hover:text-accent">
              Open →
            </span>
          </div>
          <div className="mt-2 flex gap-4 text-[11px] text-text-3 tabular">
            <span>
              <span className="text-text-1 font-semibold">
                {s.upcoming_games}
              </span>{" "}
              games
            </span>
            <span>
              <span className="text-text-1 font-semibold">
                {s.picks_today}
              </span>{" "}
              picks
            </span>
            {s.starting_in_3h > 0 && (
              <span className="text-accent">
                <span className="font-semibold">{s.starting_in_3h}</span> soon
              </span>
            )}
            {s.bet_card_date && (
              <span className="ml-auto text-text-3">
                card {s.bet_card_date}
              </span>
            )}
          </div>
        </Link>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, isLoading, isValidating, mutate } =
    useSWR<DashboardResponse>(apiPaths.dashboard, { refreshInterval: 30_000 });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <span className="text-xs text-text-3 tabular">
            everything that matters right now
          </span>
        </div>
        <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && (
        <div className="text-text-2 text-sm">Loading dashboard…</div>
      )}
      {data && (
        <>
          <MetricsStrip data={data} />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div className="lg:col-span-7">
              <TopArbsCard arbs={data.top_arbs} />
            </div>
            <div className="lg:col-span-5">
              <StartingSoonCard games={data.upcoming_games} />
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div className="lg:col-span-8">
              <TopPicksCard picks={data.top_picks} />
            </div>
            <div className="lg:col-span-4">
              <SportStatusCards sports={data.sports} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
