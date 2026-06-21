"use client";

import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { CLVChart } from "./_components/CLVChart";

export default function BetsPage() {
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: betsResp } = useSWR("/api/bets", fetchJson);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Bets</h1>
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
    </div>
  );
}
