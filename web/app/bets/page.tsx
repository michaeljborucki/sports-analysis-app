"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RefreshButton } from "@/components/refresh-button";
import { BackendUnreachable, PageHeader } from "@/components/ui";
import { RollupTiles, type Rollups as WindowRollups } from "./_components/RollupTiles";
import { Filters, type BetFilters } from "./_components/Filters";
import { Breakdowns, type Rollups as GroupRollups } from "./_components/Breakdowns";
import { BetTable, type Bet } from "./_components/BetTable";
import { ImportDrawer } from "./_components/ImportDrawer";
import { CLV_CHART_HEIGHT_CLASS } from "./_components/chart-size";

// Recharts ships a ~340KB chunk. /bets is the only page that uses it,
// and the chart sits below the fold. Dynamic import keeps it off the
// initial bundle for every other route. ssr:false because Recharts
// touches `window` at module init; we pair that with a skeleton the
// same height as the chart so the page layout doesn't jump while the
// chunk loads.
const CLVChart = dynamic(
  () => import("./_components/CLVChart").then(m => m.CLVChart),
  {
    ssr: false,
    loading: () => (
      <div
        className={`${CLV_CHART_HEIGHT_CLASS} rounded-lg border border-border-subtle bg-bg-1 animate-pulse`}
      />
    ),
  },
);

export default function BetsPage() {
  const [filters, setFilters] = useState<BetFilters>({
    book: "",
    sport: "",
    status: "",
  });
  const qs = new URLSearchParams(
    Object.entries(filters).filter(([, v]) => v),
  ).toString();
  // /api/bets/rollups returns one object carrying both the 30d/90d/lifetime
  // windows (RollupTiles) and the by_book/sport/market groups (Breakdowns);
  // the intersection is what the endpoint's RollupsResponse actually is.
  const {
    data: rollups,
    error: rollupsError,
    mutate: mutateRollups,
    isValidating: rollupsValidating,
  } = useSWR<WindowRollups & GroupRollups>("/api/bets/rollups", fetchJson);
  const {
    data: betsResp,
    error: betsError,
    mutate: mutateBets,
    isValidating: betsValidating,
  } = useSWR<{ bets: Bet[] }>(`/api/bets${qs ? `?${qs}` : ""}`, fetchJson);

  const error = rollupsError ?? betsError;
  const hasFilters = Boolean(qs);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        className="mb-0"
        title="Bets"
        description="Every bet across Coral33, Kalshi, Polymarket and imports"
        actions={
          <>
            <ImportDrawer />
            <RefreshButton
              isValidating={rollupsValidating || betsValidating}
              onRefresh={() => {
                void mutateRollups();
                void mutateBets();
              }}
            />
          </>
        }
      />
      {error && !rollups && !betsResp && <BackendUnreachable error={error} />}
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
      <Breakdowns data={rollups} />
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h2 className="text-[length:var(--fs-16)] leading-[var(--lh-16)] font-semibold text-text-1">
            Ledger
          </h2>
          <Filters value={filters} onChange={setFilters} />
          {betsResp && (
            <span className="ml-auto text-[length:var(--fs-12)] text-text-3">
              <span className="tabular">{betsResp.bets.length}</span>{" "}
              {betsResp.bets.length === 1 ? "bet" : "bets"}
              {hasFilters ? " match" : ""}
            </span>
          )}
        </div>
        <BetTable bets={betsResp?.bets} filtered={hasFilters} />
      </section>
    </div>
  );
}
