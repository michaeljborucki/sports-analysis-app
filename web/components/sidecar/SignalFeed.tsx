"use client";
import { useMemo } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Zap } from "lucide-react";

import {
  apiPaths,
  fetchJson,
  type EVResponse,
  type EVOpportunity,
} from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { formatAmerican } from "@/lib/format";
import { fromEv, marketLabel, sideLabel, commenceLabel } from "@/lib/edges";
import { AutoPlaceButton } from "./AutoPlaceButton";

/**
 * Sidecar settings shape returned by /api/sidecar/settings. Kept locally
 * (rather than importing from @/types/api) so the SignalFeed doesn't need
 * to chase deep `components["schemas"]` paths. Mirrors the Python
 * `SidecarSettingsResponse` BaseModel.
 */
export interface SidecarSettingsResponse {
  bankroll: number;
  default_kelly: "full" | "half" | "quarter";
}

/**
 * Mirrors the Python `kelly_to_pct` mapping in server/sidecar/settings.py.
 * Multiplies the full-Kelly fraction by 1 / 0.5 / 0.25 depending on the
 * user's default Kelly setting.
 */
export function kellyToPct(
  fraction: "full" | "half" | "quarter",
  fullKellyPct: number,
): number {
  if (fraction === "full") return fullKellyPct;
  if (fraction === "half") return fullKellyPct * 0.5;
  return fullKellyPct * 0.25;
}

/** Per-parlay minimum stake floor from server/sidecar/splitter.py. Below
 * this, the splitter refuses the placement (status='below_minimum'), so
 * we want to surface that visually on the SignalFeed row. */
const SIDECAR_STAKE_FLOOR = 30;

/**
 * SignalFeed — Coral33 parlay-eligible +EV stream for the sidecar
 * dashboard. Mirrors the /edges filter
 *   `wager_filter=parlay & book=coral33 & best_price=1`
 * (the third clause is implicit because the EV scanner already returns
 * one row per offered-price/market; the SignalFeed filters the response
 * down to coral33 + parlay-eligible rows).
 *
 * Each row inline-renders the existing AutoPlaceButton so the user can
 * fire a placement straight from the dashboard without bouncing to
 * /edges. Sorted by EV % descending.
 */
export function SignalFeed() {
  const { visible } = useVisibleBooks();
  const booksSorted = useMemo(() => [...visible].sort(), [visible]);

  const { data, isLoading, error } = useSWR<EVResponse>(
    apiPaths.ev(booksSorted, {
      minEv: 0,
      maxLongshotOdds: 800,
      sort: "desc",
      maxResults: 500,
      wagerFilter: "parlay",
    }),
    { refreshInterval: 60_000 },
  );

  // Single shared fetch of bankroll + default_kelly so every SignalRow
  // (and the AutoPlaceButton it renders) hits SWR's cache. Settings rarely
  // change, so a 60s refresh keeps the column accurate without thrashing.
  const { data: settings } = useSWR<SidecarSettingsResponse>(
    "/api/sidecar/settings",
    fetchJson,
    { refreshInterval: 60_000 },
  );

  const rows = useMemo(() => {
    if (!data?.opportunities) return [];
    // wager_filter=parlay already filters server-side; this guards
    // against the API returning non-coral33 rows (it shouldn't, but the
    // panel's invariant is "coral33 parlay rows only").
    return data.opportunities.filter(
      (op) => op.book === "coral33" && (op.wager_type === "parlay" || op.wager_type === "both"),
    );
  }, [data]);

  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
          <Zap size={11} aria-hidden />
          Signal feed
          <span className="text-text-2 tabular">({rows.length})</span>
        </h2>
        <span className="text-[10px] tabular text-text-3">
          coral33 · parlay-eligible · +EV
        </span>
      </header>

      {isLoading && !data && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          Scanning cache…
        </div>
      )}
      {error && (
        <div className="text-price-down text-xs px-1 py-3">
          Failed to load /api/ev
        </div>
      )}
      {!isLoading && rows.length === 0 && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          No +EV parlay-eligible signals right now.
        </div>
      )}

      {rows.length > 0 && (
        <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
          <div className="max-h-[640px] overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-bg-1 text-text-2 sticky top-0">
                <tr>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Event
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Side
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Price
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    EV
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Kelly
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Stake
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Starts
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[88px]">
                    {/* AutoPlace column */}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((op, i) => (
                  <SignalRow
                    key={`${op.ev_row_id}-${i}`}
                    op={op}
                    settings={settings}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function SignalRow({
  op,
  settings,
}: {
  op: EVOpportunity;
  settings: SidecarSettingsResponse | undefined;
}) {
  // Reuse the unified-edges labels so the dashboard reads identically to
  // /edges. fromEv() returns a fully-flattened opportunity; we hand it
  // back to marketLabel/sideLabel which already account for spreads,
  // totals, team totals, player props, alt lines, etc.
  const edge = useMemo(() => fromEv(op, 0), [op]);
  const mLabel = marketLabel(edge);
  const sLabel = sideLabel(edge);
  const evTone =
    op.ev_pct >= 5
      ? "text-price-up"
      : op.ev_pct >= 2
        ? "text-accent"
        : op.ev_pct >= 1
          ? "text-flash"
          : "text-text-2";

  // Kelly-derived dollar stake at the user's default Kelly fraction.
  // Mirrors the Python `int(round(kelly_to_pct(fraction, kelly_full_pct)
  // * bankroll))` used server-side. Renders as a placeholder until
  // settings load to avoid a layout shift.
  const stake = settings
    ? Math.round(
        kellyToPct(settings.default_kelly, op.kelly_full_pct) *
          settings.bankroll,
      )
    : null;
  const belowFloor = stake !== null && stake < SIDECAR_STAKE_FLOOR;

  return (
    <tr className="border-t border-border-subtle hover:bg-bg-1/50">
      <td className="px-2 py-1.5 align-top">
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-text-1 truncate">
            {op.home_team} vs {op.away_team}
          </span>
          <span className="text-text-3 text-[10px] uppercase tracking-wide">
            {op.sport_key} · {mLabel}
          </span>
        </div>
      </td>
      <td className="px-2 py-1.5 align-top text-text-1">
        <span className="font-medium">{sLabel}</span>
      </td>
      <td className="px-2 py-1.5 align-top text-right tabular text-price-up">
        {formatAmerican(op.offered_price_american)}
      </td>
      <td
        className={clsx(
          "px-2 py-1.5 align-top text-right tabular font-semibold",
          evTone,
        )}
      >
        {op.ev_pct >= 0 ? "+" : ""}
        {op.ev_pct.toFixed(2)}%
      </td>
      <td className="px-2 py-1.5 align-top text-right tabular text-text-2">
        {(op.kelly_full_pct * 100).toFixed(2)}%
      </td>
      <td
        className={clsx(
          "px-2 py-1.5 align-top text-right tabular",
          stake === null
            ? "text-text-3"
            : belowFloor
              ? "text-text-3 line-through"
              : "text-text-1 font-semibold",
        )}
        title={
          belowFloor
            ? `Below per-parlay floor ($${SIDECAR_STAKE_FLOOR}); will be skipped`
            : undefined
        }
      >
        {stake === null ? "—" : `$${stake.toLocaleString()}`}
      </td>
      <td className="px-2 py-1.5 align-top text-right tabular text-text-2">
        {commenceLabel(op.commence_time)}
      </td>
      <td className="px-2 py-1.5 align-top text-right">
        <AutoPlaceButton
          evRowId={op.ev_row_id}
          sportKey={op.sport_key}
          marketLabel={mLabel}
          sideLabel={sLabel}
          offeredPriceAmerican={op.offered_price_american}
          evPct={op.ev_pct}
          fullKellyPct={op.kelly_full_pct}
        />
      </td>
    </tr>
  );
}
