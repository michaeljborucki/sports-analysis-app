"use client";
import useSWR from "swr";

import { apiPaths, type DashboardResponse, type FetcherStatus } from "@/lib/api";
import { StatTile, formatAgeShort } from "@/components/ui";
import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Reference numbers for the dashboard footer: API quota, fetcher, cache.
 * Fetcher "Off" is neutral — in betting_db mode it is the expected state.
 */
export function SystemStats({ data }: { data: DashboardResponse }) {
  return (
    <section aria-label="System" className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <QuotaTile fetcher={data.fetcher} />
      <FetcherTile fetcher={data.fetcher} />
      <CacheTile scannedAt={data.scanned_at} />
    </section>
  );
}

function ageSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
}

function QuotaTile({ fetcher }: { fetcher: FetcherStatus }) {
  const remaining = fetcher.requests_remaining;
  const used = fetcher.requests_used;
  // Plan total derives from used+remaining — the Odds API tier varies per
  // account, so a hardcoded denominator gives absurd percentages.
  const total = remaining != null && used != null ? remaining + used : null;
  const pct =
    remaining != null && total && total > 0 ? Math.round((remaining / total) * 100) : null;
  const low = pct != null && pct < 20;

  return (
    <StatTile
      label="API quota remaining"
      value={remaining != null ? remaining.toLocaleString() : "—"}
      tone={low ? "stale" : undefined}
      sub={
        used != null && total != null ? (
          <>
            <span className="tabular">{used.toLocaleString()}</span> used of{" "}
            <span className="tabular">{total.toLocaleString()}</span>
            {pct != null && (
              <>
                , <span className="tabular">{pct}%</span> left
              </>
            )}
          </>
        ) : (
          "Quota unknown"
        )
      }
    />
  );
}

function FetcherTile({ fetcher }: { fetcher: FetcherStatus }) {
  const mounted = useIsMounted();
  const age = mounted ? ageSince(fetcher.last_fetch_at) : null;
  const tiers = fetcher.enabled_tiers ?? [];

  return (
    <StatTile
      label="Odds API fetcher"
      value={<span className="font-sans">{fetcher.fetcher_running ? "On" : "Off"}</span>}
      sub={
        <>
          {age != null ? (
            <>
              Last fetch <span className="tabular">{formatAgeShort(age)}</span> ago
            </>
          ) : (
            "No fetch yet"
          )}
          {tiers.length > 0 && <>, tiers: {tiers.join(", ")}</>}
        </>
      }
    />
  );
}

function CacheTile({ scannedAt }: { scannedAt: string }) {
  const mounted = useIsMounted();
  const scanAge = mounted ? ageSince(scannedAt) : null;

  // Same /api/health key as FreshnessChip, so SWR dedupes the request.
  const { data: health } = useSWR<FetcherStatus>(apiPaths.health, {
    refreshInterval: 30_000,
  });
  const priceAge = mounted ? ageSince(health?.last_fetch_at) : null;

  return (
    <StatTile
      label="Since last scan"
      value={scanAge != null ? formatAgeShort(scanAge) : "—"}
      sub={
        priceAge != null ? (
          <>
            Prices <span className="tabular">{formatAgeShort(priceAge)}</span> old
          </>
        ) : (
          "No price fetch yet"
        )
      }
    />
  );
}
