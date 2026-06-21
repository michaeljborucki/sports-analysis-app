"use client";

import useSWR from "swr";
import { fetchJson } from "@/lib/api";

// NOTE: fetchJson() in web/lib/api.ts already prepends
// NEXT_PUBLIC_API_BASE_URL — SWR keys must be relative paths.

export default function BetsPage() {
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: bets } = useSWR("/api/bets", fetchJson);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Bets</h1>
      <pre className="text-xs bg-bg-1 p-3 rounded overflow-auto">
        rollups: {JSON.stringify(rollups, null, 2)}
      </pre>
      <pre className="text-xs bg-bg-1 p-3 rounded overflow-auto max-h-96">
        bets: {JSON.stringify(bets, null, 2)}
      </pre>
    </div>
  );
}
