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
    subtitle: "Fetchers running, prices update continuously",
    icon: Radio,
  },
  latest: {
    label: "Latest",
    subtitle: "Fetchers off, showing the last prices pulled",
    icon: Pause,
  },
  snapshot: {
    label: "Snapshot",
    subtitle: "Fetchers off, showing a saved reference set",
    icon: Archive,
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
    // Low-change-rate state (the user flips this rarely, by hand).
    // 30s is plenty to surface a flip from another tab; 5s was just
    // wasted requests.
    { refreshInterval: 30_000 },
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
        type="button"
        onClick={() => setOpen(v => !v)}
        disabled={!data}
        title={data ? meta.subtitle : "Checking data source"}
        aria-haspopup="menu"
        aria-expanded={open}
        className={clsx(
          "flex w-full items-center gap-2 rounded-md px-2.5 h-8 text-left text-[length:var(--fs-13)]",
          "border border-border-subtle bg-bg-1 hover:bg-bg-2 transition-colors",
        )}
      >
        <span
          aria-hidden
          className={clsx(
            "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
            !data && "bg-text-3",
            data && mode === "live" && "live-dot",
            data && mode === "latest" && "bg-text-3",
            data && mode === "snapshot" && "bg-sharp",
          )}
        />
        <span className="flex-1 truncate text-text-1">
          {data ? `${meta.label} data` : "Checking…"}
        </span>
        <ChevronDown size={12} aria-hidden className="text-text-3" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden />
          <div
            role="menu"
            className="absolute bottom-full left-0 z-50 mb-2 w-[300px] overflow-hidden rounded-lg border border-border-subtle bg-bg-1 shadow-[0_12px_32px_rgb(0_0_0/0.45)]"
          >
            <div className="border-b border-border-subtle px-3 py-2 text-[length:var(--fs-12)] text-text-3">
              Where prices come from
            </div>
            {(Object.keys(MODE_META) as Mode[]).map(m => {
              const M = MODE_META[m];
              const MIcon = M.icon;
              const selected = mode === m;
              const disabled = m === "snapshot" && !data?.snapshot_available;
              return (
                <button
                  key={m}
                  type="button"
                  role="menuitemradio"
                  aria-checked={selected}
                  onClick={() => !disabled && setMode(m)}
                  disabled={disabled || busy !== null}
                  className={clsx(
                    "flex w-full items-start gap-3 border-b border-border-subtle px-3 py-2.5 text-left transition-colors last:border-b-0",
                    selected ? "bg-bg-2" : "hover:bg-bg-2",
                    disabled && "cursor-not-allowed opacity-40",
                    busy === `mode:${m}` && "cursor-wait opacity-60",
                  )}
                >
                  <MIcon size={14} aria-hidden className={clsx("mt-0.5 shrink-0", selected ? "text-text-1" : "text-text-3")} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[length:var(--fs-13)] font-medium text-text-1">{M.label}</span>
                      {selected && <span className="text-[length:var(--fs-11)] text-text-3">Current</span>}
                    </div>
                    <div className="mt-0.5 text-[length:var(--fs-12)] text-text-3">{M.subtitle}</div>
                    {m === "snapshot" && (
                      <div className="mt-1 text-[length:var(--fs-11)] text-text-3">
                        {data?.snapshot_available ? (
                          <>
                            <span className="tabular">{data.snapshot_row_count?.toLocaleString() ?? "?"}</span> rows, captured {formatAge(data.snapshot_captured_at)}
                          </>
                        ) : (
                          "No snapshot yet. Capture one below."
                        )}
                      </div>
                    )}
                    {m === "latest" && data?.live_newest_row_at && (
                      <div className="mt-1 text-[length:var(--fs-11)] text-text-3">
                        <span className="tabular">{data.live_row_count?.toLocaleString() ?? "?"}</span> rows, newest {formatAge(data.live_newest_row_at)}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
            <div className="border-t border-border-subtle bg-bg-0 px-3 py-2">
              <button
                type="button"
                onClick={captureSnapshot}
                disabled={busy !== null}
                className={clsx(
                  "inline-flex h-8 w-full items-center justify-center gap-2 rounded-md border border-border-subtle bg-bg-1 text-[length:var(--fs-12)] text-text-2 hover:bg-bg-2 hover:text-text-1",
                  busy === "snapshot" && "cursor-wait opacity-60",
                )}
                title="Overwrite cache.snapshot.db with a fresh copy of the live cache"
              >
                <Camera size={12} aria-hidden />
                {busy === "snapshot" ? "Capturing…" : "Capture snapshot from live"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
