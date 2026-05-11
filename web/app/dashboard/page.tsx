"use client";
import useSWR from "swr";
import { useMemo } from "react";

import {
  apiPaths,
  type ArbOpportunity,
  type DashboardResponse,
  type EVOpportunity,
  type EVResponse,
} from "@/lib/api";
import { RefreshButton } from "@/components/refresh-button";
import { FreshnessChip } from "@/components/freshness-chip";
import { useVisibleBooks } from "@/lib/use-visible-books";

import { EdgeVolumeChart } from "@/components/dashboard/edge-volume-chart";
import { SportRail } from "@/components/dashboard/sport-rail";
import { SystemStats } from "@/components/dashboard/system-stats";
import { StartingSoonCard } from "@/components/dashboard/starting-soon-card";
import { TopPicksCard } from "@/components/dashboard/top-picks-card";
import {
  TopEdgeCard,
  type TopEdgeData,
} from "@/components/dashboard/top-edge-card";

/**
 * Dashboard — the first screen on every app open.
 *
 * ## Content hierarchy (5 tiers)
 *   Tier 1 (hero)         Edge-volume 24h stacked chart — the "how the day
 *                         is going" signal, answers "is there action?"
 *   Tier 2 (primary)      Top Arb + Top +EV — the single best opportunity
 *                         right now in each mode; links to /edges.
 *   Tier 3 (rail)         Horizontal sport status chip strip — "where should
 *                         I look?" routing surface.
 *   Tier 4 (detail)       Starting Soon + Top Picks — the two other things a
 *                         user might scan in the first 10s.
 *   Tier 5 (footer)       System stats — quota, fetcher, cache. Reference
 *                         numbers, not hero metrics.
 *
 * ## Grid
 * Desktop uses `grid-template-areas` so the geometry reads left-to-right.
 * Tablet collapses to two-col with the hero full-width. Mobile stacks.
 */

// Grid area names — centralized so the grid-template-areas string below is
// legible and typo-safe.
const AREA = {
  hero: "hero",
  arb: "arb",
  ev: "ev",
  rail: "rail",
  starting: "starting",
  picks: "picks",
  footer: "footer",
} as const;

const GRID_CSS = `
.dashboard-grid {
  display: grid;
  gap: 1rem;
  grid-template-columns: 1fr;
  grid-template-areas:
    "hero"
    "arb"
    "ev"
    "rail"
    "starting"
    "picks"
    "footer";
}
@media (min-width: 768px) {
  .dashboard-grid {
    grid-template-columns: 1fr 1fr;
    grid-template-areas:
      "hero hero"
      "arb ev"
      "rail rail"
      "starting picks"
      "footer footer";
  }
}
@media (min-width: 1280px) {
  /* Hero spans 6/10 of the top two rows; the right-side pair of top-edge
     cards stack in the remaining 4/10. Rail, detail, and footer each span
     the full width. Hero has a 320px min-height floor so the chart isn't
     cramped on short viewports. */
  .dashboard-grid {
    grid-template-columns: 3fr 3fr 2fr 2fr;
    grid-template-rows: minmax(160px, auto) minmax(160px, auto) auto auto auto;
    grid-template-areas:
      "hero hero arb arb"
      "hero hero ev ev"
      "rail rail rail rail"
      "starting starting picks picks"
      "footer footer footer footer";
  }
}
.dashboard-hero {
  min-height: 320px;
}
`;

export default function DashboardPage() {
  const { visible } = useVisibleBooks();
  const booksKey = useMemo(() => [...visible].sort(), [visible]);

  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate,
  } = useSWR<DashboardResponse>(apiPaths.dashboard(booksKey), {
    refreshInterval: 30_000,
  });

  // Top +EV isn't in the dashboard response shape, so we fetch /api/ev
  // alongside and pick the best result. Same books list + same cadence.
  const { data: evData, mutate: evMutate, isValidating: evValidating } =
    useSWR<EVResponse>(
      apiPaths.ev(booksKey, { minEv: 1, maxLongshotOdds: 800 }),
      { refreshInterval: 30_000 },
    );

  const topArb: TopEdgeData | null = useMemo(
    () => (data?.top_arbs[0] ? arbToTopEdge(data.top_arbs[0]) : null),
    [data?.top_arbs],
  );
  const topEv: TopEdgeData | null = useMemo(
    () =>
      evData?.opportunities[0] ? evToTopEdge(evData.opportunities[0]) : null,
    [evData?.opportunities],
  );

  const refreshAll = () => {
    mutate();
    evMutate();
  };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-[28px] leading-[30px] font-semibold tracking-tight text-text-1">
            Dashboard
          </h1>
          <span className="text-xs text-text-3 tabular hidden sm:inline">
            everything that matters right now
          </span>
        </div>
        <div className="flex items-center gap-3">
          <FreshnessChip />
          <RefreshButton
            onRefresh={refreshAll}
            isValidating={isValidating || evValidating} />
        </div>
      </header>

      {error && (
        <div className="rounded-md border border-price-down/40 bg-price-down/10 px-4 py-3 text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && (
        <div className="rounded-md border border-border-subtle bg-bg-1 px-4 py-12 text-center text-text-2 text-sm">
          Loading dashboard…
        </div>
      )}

      {data && (
        <div className="dashboard-grid">
          {/* Tier 1: hero */}
          <section
            className="dashboard-hero relative rounded-md border border-border-subtle bg-bg-2 p-4 overflow-hidden"
            style={{ gridArea: AREA.hero }}
          >
            {/* Subtle 1px gradient top edge — marks this card as "elevated"
                without the loud glow of a full accent border. */}
            <div
              className="pointer-events-none absolute inset-x-0 top-0 h-px"
              style={{
                background:
                  "linear-gradient(90deg, transparent, var(--accent-60), transparent)",
              }}
              aria-hidden
            />
            <EdgeVolumeChart />
          </section>

          {/* Tier 2: top arb */}
          <section style={{ gridArea: AREA.arb }}>
            <TopEdgeCard
              mode="arb"
              data={topArb}
              onRefresh={refreshAll}
              isValidating={isValidating}
            />
          </section>

          {/* Tier 2: top EV */}
          <section style={{ gridArea: AREA.ev }}>
            <TopEdgeCard
              mode="ev"
              data={topEv}
              onRefresh={refreshAll}
              isValidating={evValidating}
            />
          </section>

          {/* Tier 3: sport rail */}
          <section style={{ gridArea: AREA.rail }}>
            <SportRail sports={data.sports} />
          </section>

          {/* Tier 4: starting soon */}
          <section style={{ gridArea: AREA.starting }}>
            <StartingSoonCard
              games={data.upcoming_games}
              onRefresh={refreshAll}
            />
          </section>

          {/* Tier 4: top picks */}
          <section style={{ gridArea: AREA.picks }}>
            <TopPicksCard picks={data.top_picks} onRefresh={refreshAll} />
          </section>

          {/* Tier 5: system footer */}
          <section style={{ gridArea: AREA.footer }}>
            <SystemStats data={data} />
          </section>
        </div>
      )}

      {/* Grid geometry lives in a plain <style> tag (no styled-jsx) so this
          renders identically in client/server. Tailwind v4 doesn't have a
          clean arbitrary-value syntax for grid-template-areas, so we drop
          to hand-written CSS with named areas for readability. */}
      <style dangerouslySetInnerHTML={{ __html: GRID_CSS }} />
    </div>
  );
}

// ──────────────── adapters: api shapes → TopEdgeData ────────────────

function arbToTopEdge(op: ArbOpportunity): TopEdgeData {
  const a = op.sides[0];
  const b = op.sides[1];
  return {
    sport_key: op.sport_key,
    home_team: op.home_team,
    away_team: op.away_team,
    headline_pct: op.roi_pct,
    market_label: arbMarketLabel(op.market_kind, op.point ?? null),
    books: [a?.book ?? "?", b?.book],
  };
}

function evToTopEdge(op: EVOpportunity): TopEdgeData {
  return {
    sport_key: op.sport_key,
    home_team: op.home_team,
    away_team: op.away_team,
    headline_pct: op.ev_pct,
    market_label: evMarketLabel(op),
    books: [op.book],
  };
}

function arbMarketLabel(
  kind: ArbOpportunity["market_kind"],
  point: number | null,
): string {
  if (kind === "h2h") return "Moneyline";
  if (kind === "totals") return point != null ? `Total ${point}` : "Total";
  if (kind === "spreads") return point != null ? `Spread ±${point}` : "Spread";
  return kind;
}

function evMarketLabel(op: EVOpportunity): string {
  const k = op.market_kind;
  if (k === "h2h") return `ML · ${op.outcome_name}`;
  if (k === "totals")
    return op.point != null
      ? `${op.outcome_name} ${op.point}`
      : `Total · ${op.outcome_name}`;
  if (k === "spreads")
    return op.point != null
      ? `${op.outcome_name} ${op.point > 0 ? "+" : ""}${op.point}`
      : `Spread · ${op.outcome_name}`;
  return `${k} · ${op.outcome_name}`;
}

