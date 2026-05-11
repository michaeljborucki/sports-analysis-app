"use client";
import useSWR from "swr";
import { useState } from "react";
import clsx from "clsx";
import { Zap } from "lucide-react";

import { apiPaths, fetchJson, type FetcherStatus } from "@/lib/api";

export function FetcherToggle() {
  const { data, mutate } = useSWR<FetcherStatus>(apiPaths.health, {
    refreshInterval: 5_000,
  });
  const [busy, setBusy] = useState(false);

  const running = data?.fetcher_running === true;
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

  async function toggle() {
    if (busy) return;
    setBusy(true);
    try {
      await fetch(`${base}/api/fetcher/${running ? "stop" : "start"}`, {
        method: "POST",
      });
      await mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy || !data}
      title={
        running
          ? "Fetcher is polling live — click to freeze the cache"
          : "Fetcher is frozen — click to resume live polling"
      }
      className={clsx(
        "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
        "border transition-colors",
        running
          ? "bg-price-up/10 border-price-up/40 text-price-up hover:bg-price-up/15"
          : "bg-bg-1 border-border-subtle text-text-2 hover:text-text-1",
        busy && "opacity-60 cursor-wait"
      )}
    >
      <span
        aria-hidden
        className={clsx(
          "inline-block w-1.5 h-1.5 rounded-full",
          running ? "bg-price-up live-dot" : "bg-text-3"
        )}
        style={running ? undefined : { boxShadow: "none" }}
      />
      <Zap
        size={12}
        aria-hidden
        fill={running ? "currentColor" : "none"}
        strokeWidth={1.8}
      />
      Fetcher {running ? "ON" : "OFF"}
    </button>
  );
}
