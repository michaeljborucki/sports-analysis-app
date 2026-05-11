"use client";
import useSWR from "swr";
import clsx from "clsx";
import { Database, Gauge, Server } from "lucide-react";

import { apiPaths, type DashboardResponse, type FetcherStatus } from "@/lib/api";
import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Footer system-strip for the dashboard.
 *
 * 3 cells in a dense 11px grid — quota / fetcher / cache. Each cell reads
 * small (20px numeral, not the old 28/32px KPI look) because these are
 * reference numbers, not hero metrics.
 */
export function SystemStats({ data }: { data: DashboardResponse }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <QuotaCell fetcher={data.fetcher} />
      <FetcherCell fetcher={data.fetcher} />
      <CacheCell scannedAt={data.scanned_at} />
    </div>
  );
}

function QuotaCell({ fetcher }: { fetcher: FetcherStatus }) {
  const remaining = fetcher.requests_remaining;
  const used = fetcher.requests_used;
  // Plan total derives from used+remaining — the Odds API tier varies per
  // account, so hardcoding a denominator gave absurd percentages.
  const total =
    remaining != null && used != null ? remaining + used : null;
  const pct =
    remaining != null && total && total > 0
      ? Math.round((remaining / total) * 100)
      : null;

  // Cheap "days left" estimate — assume current day's burn rate continues.
  // Without a time-series we can't project properly; show used-so-far only.
  const warn = pct != null && pct < 20;

  return (
    <Cell
      icon={<Gauge size={13} aria-hidden className="text-text-3" />}
      label="API quota"
    >
      <div className="flex items-baseline gap-2">
        <span
          className={clsx(
            "tabular text-[20px] leading-none font-semibold",
            warn ? "text-flash" : "text-text-1",
          )}
        >
          {remaining != null ? remaining.toLocaleString() : "—"}
        </span>
        {pct != null && (
          <span
            className={clsx(
              "text-[11px] tabular",
              warn ? "text-flash" : "text-text-3",
            )}
          >
            {pct}% headroom
          </span>
        )}
      </div>
      <div className="text-[10px] text-text-3 tabular">
        {used != null ? `${used.toLocaleString()} used` : "quota unknown"}
        {total != null ? ` · ${total.toLocaleString()} plan` : ""}
      </div>
    </Cell>
  );
}

function FetcherCell({ fetcher }: { fetcher: FetcherStatus }) {
  const mounted = useIsMounted();
  const lastIso = fetcher.last_fetch_at;
  const ageLabel =
    mounted && lastIso
      ? formatAge(
          Math.max(
            0,
            Math.floor((Date.now() - new Date(lastIso).getTime()) / 1000),
          ),
        )
      : "—";
  const running = fetcher.fetcher_running;
  const tiers = fetcher.enabled_tiers ?? [];

  return (
    <Cell
      icon={<Server size={13} aria-hidden className="text-text-3" />}
      label="Fetcher"
    >
      <div className="flex items-baseline gap-2">
        <span
          className={clsx(
            "inline-block w-1.5 h-1.5 rounded-full translate-y-[-2px]",
            running ? "bg-price-up" : "bg-text-3",
          )}
          aria-hidden
        />
        <span
          className={clsx(
            "text-[20px] leading-none font-semibold tracking-wide",
            running ? "text-text-1" : "text-text-2",
          )}
        >
          {running ? "On" : "Off"}
        </span>
        <span className="text-[11px] text-text-3 tabular">
          {ageLabel === "—" ? "never fetched" : `last ${ageLabel} ago`}
        </span>
      </div>
      <div className="text-[10px] text-text-3 tabular">
        {tiers.length > 0
          ? `${tiers.length} tier${tiers.length === 1 ? "" : "s"} · ${tiers.join(" · ")}`
          : "no tiers enabled"}
      </div>
    </Cell>
  );
}

function CacheCell({ scannedAt }: { scannedAt: string }) {
  const mounted = useIsMounted();
  // Freshness tied to the dashboard `scanned_at` — same signal FreshnessChip
  // uses but expressed as a whole-number age here for the stat tile.
  const scanAge = mounted
    ? Math.max(
        0,
        Math.floor((Date.now() - new Date(scannedAt).getTime()) / 1000),
      )
    : null;

  // Coral33 status is available at /api/coral33/status but we don't need it
  // here; the dashboard response freshness is the user-visible signal.
  const { data: health } = useSWR<FetcherStatus>(apiPaths.health, {
    refreshInterval: 30_000,
  });

  return (
    <Cell
      icon={<Database size={13} aria-hidden className="text-text-3" />}
      label="Cache"
    >
      <div className="flex items-baseline gap-2">
        <span className="tabular text-[20px] leading-none font-semibold text-text-1">
          {scanAge != null ? formatAge(scanAge) : "—"}
        </span>
        <span className="text-[11px] text-text-3">since last scan</span>
      </div>
      <div className="text-[10px] text-text-3 tabular">
        {health?.last_fetch_at
          ? `prices ${formatAge(
              Math.max(
                0,
                Math.floor(
                  (Date.now() - new Date(health.last_fetch_at).getTime()) /
                    1000,
                ),
              ),
            )} old`
          : "no fetch yet"}
      </div>
    </Cell>
  );
}

function Cell({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border-subtle bg-bg-1 p-3 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-3">
        {icon}
        <span>{label}</span>
      </div>
      {children}
    </div>
  );
}

function formatAge(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h`;
  return `${Math.round(sec / 86400)}d`;
}
