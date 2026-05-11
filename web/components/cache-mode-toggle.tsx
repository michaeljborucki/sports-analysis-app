"use client";
import { useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Archive, Camera, ChevronDown, Pause, Radio } from "lucide-react";

/**
 * Cache-mode toggle — replaces the old binary Fetcher ON/OFF. Three modes:
 *
 *   LIVE       — both fetchers running, reads the rolling cache.db
 *   LATEST     — fetchers off, reads the same cache.db (frozen snapshot
 *                of the last pulled data)
 *   SNAPSHOT   — fetchers off, reads cache.snapshot.db (a reproducible
 *                reference set, captured via POST /api/cache-snapshot)
 *
 * Clicking the chip opens a popover with the three modes + a one-line
 * explainer + a "Capture snapshot from live cache" action that writes the
 * current live cache into the snapshot file (no mode change).
 */

interface CacheModeStatus {
  mode: "live" | "latest" | "snapshot";
  snapshot_available: boolean;
  snapshot_captured_at: string | null;
  snapshot_newest_row_at: string | null;
  snapshot_row_count: number | null;
  live_newest_row_at: string | null;
  live_row_count: number | null;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

const MODE_META = {
  live: {
    label: "Live",
    subtitle: "Both fetchers running · reads rolling cache",
    icon: Radio,
    tone: "price-up",
  },
  latest: {
    label: "Latest",
    subtitle: "Fetchers off · reads last-pulled cache",
    icon: Pause,
    tone: "text-2",
  },
  snapshot: {
    label: "Snapshot",
    subtitle: "Fetchers off · reads captured reference set",
    icon: Archive,
    tone: "violet-accent",
  },
} as const;

type Mode = keyof typeof MODE_META;

function formatAge(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function CacheModeToggle() {
  const { data, mutate } = useSWR<CacheModeStatus>(
    "/api/cache-mode",
    fetchJson,
    { refreshInterval: 5_000 },
  );
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const mode: Mode = data?.mode ?? "latest";
  const meta = MODE_META[mode];
  const Icon = meta.icon;

  async function setMode(next: Mode) {
    if (busy) return;
    setBusy(`mode:${next}`);
    try {
      await fetch(`${API_BASE}/api/cache-mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: next }),
      });
      await mutate();
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  async function captureSnapshot() {
    if (busy) return;
    setBusy("snapshot");
    try {
      await fetch(`${API_BASE}/api/cache-snapshot`, { method: "POST" });
      await mutate();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        disabled={!data}
        title={meta.subtitle}
        className={clsx(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
          "border transition-colors",
          mode === "live" &&
            "bg-price-up/10 border-price-up/40 text-price-up hover:bg-price-up/15",
          mode === "latest" &&
            "bg-bg-1 border-border-subtle text-text-2 hover:text-text-1",
          mode === "snapshot" &&
            "bg-violet-accent/10 border-violet-accent/40 text-violet-accent hover:bg-violet-accent/15",
        )}
      >
        <span
          aria-hidden
          className={clsx(
            "inline-block w-1.5 h-1.5 rounded-full",
            mode === "live" && "bg-price-up live-dot",
            mode === "latest" && "bg-text-3",
            mode === "snapshot" && "bg-violet-accent",
          )}
        />
        <Icon size={12} aria-hidden strokeWidth={1.8} />
        <span className="uppercase tracking-wide text-[11px]">
          {meta.label}
        </span>
        <ChevronDown size={10} aria-hidden className="text-text-3" />
      </button>

      {open && (
        <>
          {/* click-outside scrim */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute right-0 top-9 z-50 w-[320px] rounded-lg border border-border-subtle bg-bg-1 shadow-2xl overflow-hidden">
            <div className="px-3 py-2 border-b border-border-subtle text-[10px] uppercase tracking-wider text-text-3">
              Cache source
            </div>
            {(Object.keys(MODE_META) as Mode[]).map(m => {
              const M = MODE_META[m];
              const MIcon = M.icon;
              const selected = mode === m;
              const disabled = m === "snapshot" && !data?.snapshot_available;
              return (
                <button
                  key={m}
                  onClick={() => !disabled && setMode(m)}
                  disabled={disabled || busy !== null}
                  className={clsx(
                    "w-full flex items-start gap-3 px-3 py-2.5 text-left transition-colors",
                    "border-b border-border-subtle/60 last:border-b-0",
                    selected ? "bg-bg-2" : "hover:bg-bg-2/60",
                    disabled && "opacity-40 cursor-not-allowed",
                    busy === `mode:${m}` && "opacity-60 cursor-wait",
                  )}
                >
                  <MIcon
                    size={14}
                    aria-hidden
                    className={clsx(
                      "mt-0.5 shrink-0",
                      selected ? "text-text-1" : "text-text-3",
                    )}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium text-text-1">
                        {M.label}
                      </span>
                      {selected && (
                        <span className="text-[9px] uppercase tracking-wider text-accent">
                          active
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-text-3 mt-0.5">
                      {M.subtitle}
                    </div>
                    {m === "snapshot" && (
                      <div className="text-[10px] text-text-3 mt-1 tabular">
                        {data?.snapshot_available
                          ? `${data.snapshot_row_count?.toLocaleString() ?? "?"} rows · captured ${formatAge(data.snapshot_captured_at)}`
                          : "no snapshot yet — capture below"}
                      </div>
                    )}
                    {m === "latest" && data?.live_newest_row_at && (
                      <div className="text-[10px] text-text-3 mt-1 tabular">
                        {data.live_row_count?.toLocaleString() ?? "?"} rows · newest {formatAge(data.live_newest_row_at)}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
            <div className="px-3 py-2 border-t border-border-subtle bg-bg-0">
              <button
                onClick={captureSnapshot}
                disabled={busy !== null}
                className={clsx(
                  "w-full inline-flex items-center justify-center gap-2 h-7 rounded-md text-[11px]",
                  "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1 hover:border-accent/50",
                  busy === "snapshot" && "opacity-60 cursor-wait",
                )}
                title="Overwrite cache.snapshot.db with a fresh copy of the live cache"
              >
                <Camera size={11} aria-hidden />
                {busy === "snapshot" ? "Capturing…" : "Capture snapshot from live"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
