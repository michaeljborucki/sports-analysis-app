"use client";
import { useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Power } from "lucide-react";

import { fetchJson } from "@/lib/api";

type SidecarMode = "off" | "dry-run" | "live";

interface ModeResponse {
  mode: SidecarMode;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const OPTIONS: { value: SidecarMode; label: string; description: string }[] = [
  { value: "off",     label: "Off",     description: "No new placements (in-flight finish, no successors run)." },
  { value: "dry-run", label: "Dry-run", description: "Full placement path with the final insertWagerParlay call short-circuited." },
  { value: "live",    label: "Live",    description: "Real placements via insertWagerParlay." },
];

/**
 * ModeToggle — three-way segmented control for the sidecar's master gate.
 * Reads /api/sidecar/mode (refresh every 5s so a flip in another tab
 * surfaces here) and POSTs the next mode on click.
 *
 * Palette per spec:
 *   - off  active = muted gray
 *   - dry  active = muted yellow (flash)
 *   - live active = saturated green (price-up)
 *   - inactive  = subdued text-3 on bg-1
 *
 * The endpoint is shipping in Phase F; until then, clicking does the
 * POST and the SWR refetch picks up the new mode on the next tick.
 */
export function ModeToggle() {
  const { data, mutate, isLoading } = useSWR<ModeResponse>(
    "/api/sidecar/mode",
    fetchJson,
    { refreshInterval: 5_000 },
  );
  const [busy, setBusy] = useState<SidecarMode | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const current: SidecarMode = data?.mode ?? "off";

  async function setMode(next: SidecarMode) {
    if (next === current || busy) return;
    setBusy(next);
    setErr(null);
    try {
      const res = await fetch(`${API_BASE}/api/sidecar/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: next }),
      });
      if (!res.ok) throw new Error(`POST /api/sidecar/mode → ${res.status}`);
      await mutate({ mode: next }, { revalidate: true });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
        <Power size={11} aria-hidden />
        Sidecar
      </span>
      <div
        role="radiogroup"
        aria-label="Sidecar mode"
        className="inline-flex rounded-md border border-border-subtle bg-bg-1 p-0.5"
      >
        {OPTIONS.map((opt) => {
          const active = opt.value === current;
          const tone = optionToneClass(opt.value, active);
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={busy !== null || isLoading}
              onClick={() => setMode(opt.value)}
              title={opt.description}
              className={clsx(
                "px-2.5 py-1 text-[11px] font-semibold tracking-wider uppercase rounded-sm transition-colors",
                tone,
                busy === opt.value && "animate-pulse",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      {err && (
        <span className="text-price-down text-[10px] tabular truncate max-w-[200px]" title={err}>
          {err}
        </span>
      )}
    </div>
  );
}

function optionToneClass(value: SidecarMode, active: boolean): string {
  if (!active) return "text-text-3 hover:text-text-1 hover:bg-bg-2";
  switch (value) {
    case "off":
      return "bg-bg-2 text-text-2";
    case "dry-run":
      return "bg-flash/20 text-flash";
    case "live":
      return "bg-price-up text-bg-0";
  }
}
