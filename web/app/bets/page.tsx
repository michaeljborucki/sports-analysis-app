"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { CLVChart } from "./_components/CLVChart";
import { Filters, type BetFilters } from "./_components/Filters";
import { Breakdowns } from "./_components/Breakdowns";
import { BetTable } from "./_components/BetTable";
import { ImportDrawer } from "./_components/ImportDrawer";

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
