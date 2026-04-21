"use client";
import { useState } from "react";
import clsx from "clsx";
import useSWRMutation from "swr/mutation";

import type { Game } from "@/lib/api";
import { refreshEventUrl } from "@/lib/api";
import type { Sport, MarketGroup } from "@/lib/sports";
import { AltLinesMatrix } from "../alt-lines-matrix";


const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function postRefresh(url: string) {
  const res = await fetch(`${API_BASE}${url}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}


/**
 * Game-row expansion drawer on the odds grid. Shows a unified book-by-book
 * matrix of mains + alt lines for the active market group, with sub-tabs to
 * switch between Spreads / Totals / Team Totals (driven by Settings).
 * Mainline row gets a MAIN badge; best price per sub-row is tinted.
 *
 * For the moneyline market group (no alts exist by convention), we render a
 * minimal summary — the main grid already shows the best ML; if the user
 * wants per-book ML breakdown we could extend here but for now we'd only
 * duplicate the main grid.
 */
export function MarketExpansionPanel({
  game,
  sport,
  group,
  visible,
}: {
  game: Game;
  sport: Sport;
  /** The market tab currently selected in the main grid — seeds the sub-tab. */
  group: MarketGroup;
  visible: Set<string>;
}) {
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

  // Moneyline has no alt ladder — the main grid already surfaces the best
  // ML; an expansion panel showing one row × many books is redundant here.
  // Show a subtle notice and the refresh button only.
  if (group.display === "moneyline") {
    return (
      <div className="p-4 bg-bg-1/40 border-l-2 border-accent/60 flex items-center justify-between">
        <span className="text-[11px] text-text-3">
          No alt lines for moneyline markets. Use the Spread or Total tab for
          per-book line shopping.
        </span>
        <RefreshButton
          onClick={handleRefresh}
          busy={isMutating}
          status={status}
        />
      </div>
    );
  }

  return (
    <div className="p-4 bg-bg-1/40 border-l-2 border-accent/60 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          Mains + alts — book by book
        </span>
        <RefreshButton
          onClick={handleRefresh}
          busy={isMutating}
          status={status}
        />
      </div>

      <AltLinesMatrix
        game={game}
        sport={sport}
        visible={visible}
        outerMarketKey={group.mainKey}
      />
    </div>
  );
}


function RefreshButton({
  onClick,
  busy,
  status,
}: {
  onClick: () => void;
  busy: boolean;
  status: string | null;
}) {
  return (
    <div className="ml-auto inline-flex items-center gap-2">
      {status && <span className="text-[10px] text-accent tabular">{status}</span>}
      <button
        onClick={onClick}
        disabled={busy}
        className={clsx(
          "inline-flex items-center gap-1.5 h-7 px-2 rounded-sm text-[10px] font-medium",
          "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1",
          busy && "opacity-60 cursor-wait"
        )}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 16 16"
          fill="none"
          className={clsx(busy && "animate-spin")}
          aria-hidden
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
    </div>
  );
}
