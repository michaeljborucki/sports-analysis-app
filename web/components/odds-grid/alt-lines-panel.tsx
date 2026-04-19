"use client";
import { useState } from "react";
import clsx from "clsx";
import useSWRMutation from "swr/mutation";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { refreshEventUrl } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { findAllBest } from "@/lib/consensus";
import { BookLogo } from "../book-logo";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function postRefresh(url: string) {
  const res = await fetch(`${API_BASE}${url}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function findMarket(game: Game, key: string): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

/**
 * One row per unique (outcome_name, point) tuple, sorted so favorites' positive
 * / underdogs' negative scale cleanly. For alt_spreads: (team, point). For
 * alt_totals: (Over|Under, point).
 */
function groupByPoint(outcomes: MarketOutcome[] | undefined): MarketOutcome[] {
  if (!outcomes) return [];
  return [...outcomes].sort((a, b) => {
    // Primary sort by outcome name, secondary by point
    const an = a.outcome_name ?? "";
    const bn = b.outcome_name ?? "";
    if (an !== bn) return an.localeCompare(bn);
    const ap = a.best_price?.point ?? a.prices[0]?.point ?? 0;
    const bp = b.best_price?.point ?? b.prices[0]?.point ?? 0;
    return ap - bp;
  });
}

function AltRow({ outcome }: { outcome: MarketOutcome }) {
  const tied = findAllBest(outcome.prices);
  const best = tied[0];
  const point = best?.point ?? outcome.prices[0]?.point ?? null;
  return (
    <tr className="border-t border-border-subtle/40 hover:bg-bg-1/40">
      <td className="px-2 py-1.5 text-text-1 tabular whitespace-nowrap">
        {outcome.outcome_name}
        {point != null && (
          <span className="text-text-2 ml-1">
            {point > 0 ? `+${point}` : point}
          </span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right tabular">
        {best ? (
          <span className="inline-flex items-baseline gap-1">
            <span className="text-price-up font-semibold">
              {formatAmerican(best.price_american)}
            </span>
            <BookLogo bookKey={best.bookmaker_key} mode="label" />
          </span>
        ) : (
          <span className="text-text-3">—</span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right text-text-3 tabular">
        {outcome.consensus_price_american != null
          ? formatAmerican(outcome.consensus_price_american)
          : "—"}
      </td>
      <td className="px-2 py-1.5 text-text-3 text-[10px] tabular">
        {outcome.prices.length} book{outcome.prices.length === 1 ? "" : "s"}
      </td>
    </tr>
  );
}

function AltSection({
  title,
  outcomes,
}: {
  title: string;
  outcomes: MarketOutcome[];
}) {
  if (!outcomes.length) {
    return (
      <div>
        <div className="text-[11px] uppercase tracking-wider text-text-3 mb-1">
          {title}
        </div>
        <div className="text-text-3 text-xs">No alt lines cached.</div>
      </div>
    );
  }
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-text-3 mb-1">
        {title}{" "}
        <span className="text-text-3/70">· {outcomes.length} lines</span>
      </div>
      <div className="border border-border-subtle rounded-md overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Side / Line
              </th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Best
              </th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Consensus
              </th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Depth
              </th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((o, i) => (
              <AltRow
                key={`${o.outcome_name}-${o.best_price?.point ?? i}`}
                outcome={o}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AltLinesPanel({ game }: { game: Game }) {
  const altSpreads = findMarket(game, "alternate_spreads");
  const altTotals = findMarket(game, "alternate_totals");
  const f5Spreads = findMarket(game, "spreads_1st_5_innings");
  const f5Totals = findMarket(game, "totals_1st_5_innings");
  const f5H2h = findMarket(game, "h2h_1st_5_innings");

  const [status, setStatus] = useState<string | null>(null);
  const { trigger, isMutating } = useSWRMutation(
    refreshEventUrl(game.event_id),
    (url: string) => postRefresh(url)
  );

  async function handleRefresh() {
    try {
      const r = await trigger();
      setStatus(
        r.status === "debounced"
          ? `Debounced — retry in ${r.retry_after_seconds}s`
          : `Refreshed: ${(r.polled ?? []).join(", ") || "—"}`
      );
      setTimeout(() => setStatus(null), 4000);
    } catch {
      setStatus("Refresh failed");
      setTimeout(() => setStatus(null), 3000);
    }
  }

  return (
    <div className="p-4 bg-bg-1/40 border-l-2 border-accent/60 flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          Alternate lines & inning markets
        </span>
        <button
          onClick={handleRefresh}
          disabled={isMutating}
          className={clsx(
            "ml-auto inline-flex items-center gap-1.5 h-6 px-2 rounded-sm text-[10px] font-medium",
            "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1",
            isMutating && "opacity-60 cursor-wait"
          )}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 16 16"
            fill="none"
            className={clsx(isMutating && "animate-spin")}
          >
            <path
              d="M3 8a5 5 0 0 1 8.5-3.5l1-1M13 8a5 5 0 0 1-8.5 3.5l-1 1M11.5 4.5v-3h3M4.5 11.5v3h-3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Refresh this game
        </button>
        {status && <span className="text-[10px] text-accent">{status}</span>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <AltSection
          title="Alt Spreads"
          outcomes={groupByPoint(altSpreads?.outcomes)}
        />
        <AltSection
          title="Alt Totals"
          outcomes={groupByPoint(altTotals?.outcomes)}
        />
      </div>

      {(f5H2h || f5Spreads || f5Totals) && (
        <div className="grid grid-cols-3 gap-4">
          <AltSection
            title="F5 Moneyline"
            outcomes={groupByPoint(f5H2h?.outcomes)}
          />
          <AltSection
            title="F5 Run Line"
            outcomes={groupByPoint(f5Spreads?.outcomes)}
          />
          <AltSection
            title="F5 Total"
            outcomes={groupByPoint(f5Totals?.outcomes)}
          />
        </div>
      )}
    </div>
  );
}
