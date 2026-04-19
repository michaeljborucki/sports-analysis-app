"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import {
  apiPaths,
  type SettingsResponse,
  type SportOption,
  type TierOption,
  type MarketOption,
} from "@/lib/api";
import { RefreshButton } from "@/components/refresh-button";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const TIER_LABELS: Record<string, string> = {
  main: "Main Markets",
  alternates: "Alternate Lines",
  periods: "Period / Inning Markets",
  player_props: "Player Props",
};

// Per-sport override for the "periods" tier (structure varies by sport).
const PERIOD_LABEL_BY_SPORT: Record<string, string> = {
  mlb: "First Innings (F5 / F3 / F1 / F7)",
  baseball_ncaa: "First Innings (F5 / F3 / F1)",
  nba: "Quarters & Halves",
  nhl: "Periods (P1 / P2 / P3)",
};

function tierLabel(tierName: string, sportKey: string): string {
  if (tierName === "periods") {
    return PERIOD_LABEL_BY_SPORT[sportKey] ?? TIER_LABELS.periods;
  }
  return TIER_LABELS[tierName] ?? tierName;
}

function formatMarketKey(key: string): string {
  // Make Odds-API keys human-readable: pitcher_strikeouts → "Pitcher Strikeouts"
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\b(H2h|1St|Ml)\b/gi, m => m.toUpperCase());
}

/**
 * Tri-state checkbox: on / off / mixed.
 *
 * Renders as a `<span>` so it can safely live inside a parent `<button>`
 * (React 19 hard-errors on nested native buttons and that can block
 * hydration in dev). The parent element's click handler drives the toggle.
 */
function TriCheckbox({ state }: { state: "on" | "off" | "mixed" }) {
  return (
    <span
      role="checkbox"
      aria-checked={state === "on" ? "true" : state === "mixed" ? "mixed" : "false"}
      className={clsx(
        "inline-flex w-3.5 h-3.5 rounded-sm border items-center justify-center text-[10px] font-bold",
        "transition-colors flex-shrink-0",
        state === "on" && "bg-accent border-accent text-bg-0",
        state === "mixed" && "bg-accent/40 border-accent text-bg-0",
        state === "off" && "border-text-3"
      )}
    >
      {state === "on" ? "✓" : state === "mixed" ? "–" : ""}
    </span>
  );
}

export default function SettingsPage() {
  const { data, error, isLoading, isValidating, mutate } =
    useSWR<SettingsResponse>(apiPaths.settings, { refreshInterval: 0 });

  // Editable draft that diverges from `data` while the user makes changes.
  const [disabledSports, setDisabledSports] = useState<Set<string>>(new Set());
  const [disabledMarkets, setDisabledMarkets] = useState<
    Record<string, Set<string>>
  >({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  // Seed draft state from server on load or refresh
  useEffect(() => {
    if (!data) return;
    setDisabledSports(new Set(data.disabled_sports));
    const dm: Record<string, Set<string>> = {};
    for (const [sport, keys] of Object.entries(data.disabled_markets) as [
      string,
      string[],
    ][]) {
      dm[sport] = new Set(keys);
    }
    setDisabledMarkets(dm);
  }, [data]);

  const dirty = useMemo(() => {
    if (!data) return false;
    const serverSports = new Set(data.disabled_sports);
    if (serverSports.size !== disabledSports.size) return true;
    for (const k of serverSports) if (!disabledSports.has(k)) return true;

    const serverMarkets = data.disabled_markets;
    const draftSports = new Set([
      ...Object.keys(serverMarkets),
      ...Object.keys(disabledMarkets),
    ]);
    for (const sport of draftSports) {
      const srv = new Set(serverMarkets[sport] ?? []);
      const draft = disabledMarkets[sport] ?? new Set<string>();
      if (srv.size !== draft.size) return true;
      for (const k of srv) if (!draft.has(k)) return true;
    }
    return false;
  }, [data, disabledSports, disabledMarkets]);

  function toggleSport(key: string) {
    const next = new Set(disabledSports);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setDisabledSports(next);
  }

  function toggleMarket(sportKey: string, marketKey: string) {
    const current = new Set(disabledMarkets[sportKey] ?? []);
    if (current.has(marketKey)) current.delete(marketKey);
    else current.add(marketKey);
    setDisabledMarkets({ ...disabledMarkets, [sportKey]: current });
  }

  function setTierState(sport: SportOption, tierName: string, enable: boolean) {
    const tier = sport.tiers.find((t: TierOption) => t.name === tierName);
    if (!tier) return;
    const current = new Set(disabledMarkets[sport.key] ?? []);
    for (const m of tier.markets as MarketOption[]) {
      if (enable) current.delete(m.key);
      else current.add(m.key);
    }
    setDisabledMarkets({ ...disabledMarkets, [sport.key]: current });
  }

  function tierState(
    sport: SportOption,
    tierName: string
  ): "on" | "off" | "mixed" {
    const tier = sport.tiers.find((t: TierOption) => t.name === tierName);
    if (!tier || tier.markets.length === 0) return "off";
    const disabled = disabledMarkets[sport.key] ?? new Set<string>();
    const disabledCount = tier.markets.filter((m: MarketOption) =>
      disabled.has(m.key)
    ).length;
    if (disabledCount === 0) return "on";
    if (disabledCount === tier.markets.length) return "off";
    return "mixed";
  }

  function toggleExpanded(sportKey: string) {
    const next = new Set(expanded);
    if (next.has(sportKey)) next.delete(sportKey);
    else next.add(sportKey);
    setExpanded(next);
  }

  async function save() {
    if (!dirty) return;
    setSaving(true);
    try {
      const body = {
        disabled_sports: [...disabledSports],
        disabled_markets: Object.fromEntries(
          Object.entries(disabledMarkets).map(([k, v]) => [k, [...v]])
        ),
      };
      const res = await fetch(`${API_BASE}${apiPaths.settings}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const payload = await res.json();
      setSavedNotice(
        payload.reload_status === "started"
          ? "Saved — fetcher restarted with new settings"
          : payload.reload_status === "not_running"
          ? "Saved — fetcher is off; changes apply on next start"
          : "Saved"
      );
      setTimeout(() => setSavedNotice(null), 5000);
      await mutate();
    } catch (e) {
      setSavedNotice("Save failed");
      setTimeout(() => setSavedNotice(null), 4000);
    } finally {
      setSaving(false);
    }
  }

  function reset() {
    if (!data) return;
    setDisabledSports(new Set(data.disabled_sports));
    const dm: Record<string, Set<string>> = {};
    for (const [sport, keys] of Object.entries(data.disabled_markets) as [
      string,
      string[],
    ][]) {
      dm[sport] = new Set(keys);
    }
    setDisabledMarkets(dm);
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <span className="text-xs text-text-3 tabular max-w-xl">
            Toggle sports and markets off to skip them in the fetcher. Saves
            hot-reload the running fetcher — no backend restart needed.
          </span>
        </div>
        <div className="flex items-center gap-3">
          {savedNotice && (
            <span className="text-[11px] text-accent tabular">
              {savedNotice}
            </span>
          )}
          {dirty && (
            <button
              onClick={reset}
              className="h-8 px-3 rounded-md text-xs font-medium border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1"
            >
              Reset
            </button>
          )}
          <button
            onClick={save}
            disabled={!dirty || saving}
            className={clsx(
              "h-8 px-4 rounded-md text-xs font-medium border transition-colors",
              dirty
                ? "bg-accent/15 border-accent/50 text-accent hover:bg-accent/20"
                : "bg-bg-1 border-border-subtle text-text-3 cursor-default",
              saving && "opacity-60 cursor-wait"
            )}
          >
            {saving ? "Saving…" : dirty ? "Save changes" : "No changes"}
          </button>
          <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
        </div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && (
        <div className="text-text-2 text-sm">Loading settings…</div>
      )}

      {data && (
        <div className="flex flex-col gap-3">
          {data.sports.map((sport: SportOption) => {
            const sportOn = !disabledSports.has(sport.key);
            const isExpanded = expanded.has(sport.key);
            return (
              <div
                key={sport.key}
                className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden"
              >
                <div className="flex items-center gap-3 px-4 py-3 bg-bg-1 border-b border-border-subtle">
                  <button
                    onClick={() => toggleSport(sport.key)}
                    className="flex-shrink-0 cursor-pointer"
                    aria-label={`${sportOn ? "Disable" : "Enable"} ${sport.label}`}
                  >
                    <TriCheckbox state={sportOn ? "on" : "off"} />
                  </button>
                  <span className="text-sm font-semibold text-text-1">
                    {sport.label}
                  </span>
                  <span className="text-[11px] text-text-3 tabular">
                    {sport.tiers.length} tier{sport.tiers.length === 1 ? "" : "s"} ·{" "}
                    {sport.tiers.reduce(
                      (n: number, t: TierOption) => n + t.markets.length,
                      0
                    )}{" "}
                    markets
                  </span>
                  <button
                    onClick={() => toggleExpanded(sport.key)}
                    className="ml-auto text-[11px] text-text-2 hover:text-text-1 uppercase tracking-wide"
                  >
                    {isExpanded ? "Collapse" : "Expand"}
                  </button>
                </div>
                {isExpanded && (
                  <div className={clsx(
                    "flex flex-col divide-y divide-border-subtle",
                    !sportOn && "opacity-50"
                  )}>
                    {sport.tiers.map((tier: TierOption) => {
                      const state = tierState(sport, tier.name);
                      return (
                        <div key={tier.name} className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <button
                              onClick={() =>
                                setTierState(sport, tier.name, state !== "on")
                              }
                              className="flex-shrink-0 cursor-pointer"
                              aria-label={`Toggle ${tier.name}`}
                            >
                              <TriCheckbox state={state} />
                            </button>
                            <span className="text-xs font-semibold text-text-1">
                              {tierLabel(tier.name, sport.key)}
                            </span>
                            <span className="text-[10px] text-text-3 tabular uppercase tracking-wide">
                              {tier.interval_seconds}s
                              {!tier.enabled_in_config && (
                                <span className="ml-2 text-flash">config off</span>
                              )}
                            </span>
                          </div>
                          <div className="mt-2 pl-7 flex flex-wrap gap-x-4 gap-y-1">
                            {tier.markets.map((market: MarketOption) => {
                              const disabled =
                                disabledMarkets[sport.key]?.has(market.key) ??
                                false;
                              return (
                                <button
                                  key={market.key}
                                  onClick={() =>
                                    toggleMarket(sport.key, market.key)
                                  }
                                  className={clsx(
                                    "inline-flex items-center gap-2 py-1 text-[11px] transition-colors",
                                    disabled
                                      ? "text-text-3"
                                      : "text-text-2 hover:text-text-1"
                                  )}
                                >
                                  <TriCheckbox
                                    state={disabled ? "off" : "on"}
                                  />
                                  <span className="tabular">
                                    {formatMarketKey(market.key)}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
