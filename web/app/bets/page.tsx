"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { CLVChart } from "./_components/CLVChart";
import { Filters, type BetFilters } from "./_components/Filters";
import { Breakdowns } from "./_components/Breakdowns";

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
      <h1 className="text-2xl font-semibold">Bets</h1>
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
      <Breakdowns data={rollups} />
      <Filters value={filters} onChange={setFilters} />
    </div>
  );
}
