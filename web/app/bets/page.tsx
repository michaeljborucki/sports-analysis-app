"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { Filters, type BetFilters } from "./_components/Filters";
import { Breakdowns } from "./_components/Breakdowns";
import { BetTable } from "./_components/BetTable";
import { ImportDrawer } from "./_components/ImportDrawer";

// Recharts ships a ~340KB chunk. /bets is the only page that uses it,
// and the chart sits below the fold. Dynamic import keeps it off the
// initial bundle for every other route. ssr:false because Recharts
// touches `window` at module init; we pair that with a skeleton so the
// page layout doesn't jump while the chunk loads.
const CLVChart = dynamic(
  () => import("./_components/CLVChart").then(m => m.CLVChart),
  {
    ssr: false,
    loading: () => (
      <div className="h-[300px] bg-bg-1 rounded animate-pulse" />
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
    Object.entries(filters).filter(([_, v]) => v),
  ).toString();
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: betsResp } = useSWR(
    `/api/bets${qs ? `?${qs}` : ""}`,
    fetchJson,
  );

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Bets</h1>
        <ImportDrawer />
      </div>
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
      <Breakdowns data={rollups} />
      <Filters value={filters} onChange={setFilters} />
      <BetTable bets={betsResp?.bets} />
    </div>
  );
}
