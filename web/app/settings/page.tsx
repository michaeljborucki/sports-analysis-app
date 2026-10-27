"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Check, ChevronDown, ChevronRight, Minus, Save } from "lucide-react";

import {
  apiPaths,
  type SettingsResponse,
  type SportOption,
  type TierOption,
  type MarketOption,
} from "@/lib/api";
import { RefreshButton } from "@/components/refresh-button";
import { BookVisibilitySettings } from "@/components/book-visibility-settings";
import { Coral33RefreshButton } from "@/components/coral33-refresh-button";
import { DensityToggle } from "@/components/density-toggle";
import { BackendUnreachable, Chip, Panel, PageHeader } from "@/components/ui";
import { DEFAULT_VISIBLE_BOOKS } from "@/lib/books";
import { useVisibleBooks } from "@/lib/use-visible-books";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const TIER_LABELS: Record<string, string> = {
  main: "Main markets",
  alternates: "Alternate lines",
  periods: "Period and inning markets",
  player_props: "Player props",
};

// Per-sport override for the "periods" tier (structure varies by sport).
const PERIOD_LABEL_BY_SPORT: Record<string, string> = {
  mlb: "First innings (F5, F3, F1, F7)",
  baseball_ncaa: "First innings (F5, F3, F1)",
  nba: "Quarters and halves",
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
        "inline-flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border transition-colors",
        state === "on" && "border-text-1 bg-text-1 text-bg-0",
        state === "mixed" && "border-text-2 bg-bg-2 text-text-1",
        state === "off" && "border-text-3 bg-transparent"
      )}
    >
      {state === "on" ? (
        <Check size={11} strokeWidth={3} aria-hidden />
      ) : state === "mixed" ? (
        <Minus size={11} strokeWidth={3} aria-hidden />
      ) : null}
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
  const [visibleBooks, setVisibleBooks] = useState<Set<string>>(
    new Set(DEFAULT_VISIBLE_BOOKS)
  );
  // Exchange liquidity floor ($) for the edge scanners. 0 = off.
  const [minLiquidity, setMinLiquidity] = useState<number>(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  // Used post-save to sync localStorage so every other page (which reads via
  // useVisibleBooks) picks up the new set immediately.
  const { visible: currentVisible, setAll: setLocalVisible } = useVisibleBooks();

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
    setMinLiquidity(data.min_liquidity_dollars ?? 0);
    // visible_books: backend source of truth if present, else fall back to the
    // running client's localStorage-backed set (which on first-ever install
    // equals DEFAULT_VISIBLE_BOOKS).
    if (data.visible_books && data.visible_books.length >= 0) {
      const next = new Set(data.visible_books);
      setVisibleBooks(next);
      setLocalVisible([...next]);
    } else {
      setVisibleBooks(new Set(currentVisible));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

    // visible_books dirty check — compare to whatever the server last said
    // (falling back to the live localStorage state when server has no value).
    const serverBooks = new Set(
      data.visible_books ?? [...currentVisible]
    );
    if (serverBooks.size !== visibleBooks.size) return true;
    for (const k of serverBooks) if (!visibleBooks.has(k)) return true;

    if ((data.min_liquidity_dollars ?? 0) !== minLiquidity) return true;

    return false;
  }, [data, disabledSports, disabledMarkets, visibleBooks, currentVisible, minLiquidity]);

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
        visible_books: [...visibleBooks],
        min_liquidity_dollars: minLiquidity,
      };
      const res = await fetch(`${API_BASE}${apiPaths.settings}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const payload = await res.json();
      // Sync the visible books to localStorage so the rest of the app (odds
      // grid, arb, EV, etc.) picks them up immediately without a page reload.
      setLocalVisible([...visibleBooks]);
      setSavedNotice(
        payload.reload_status === "started"
          ? "Saved — fetcher restarted with new settings"
          : payload.reload_status === "not_running"
          ? "Saved — fetcher is off; changes apply on next start"
          : "Saved"
      );
      setTimeout(() => setSavedNotice(null), 5000);
      await mutate();
    } catch {
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
    setMinLiquidity(data.min_liquidity_dollars ?? 0);
    const serverBooks = data.visible_books;
    setVisibleBooks(
      new Set(serverBooks ?? [...currentVisible])
    );
  }

  const marketCount = (sport: SportOption) =>
    sport.tiers.reduce((n: number, t: TierOption) => n + t.markets.length, 0);

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Settings"
        description="Turn sports and markets off to skip them in the fetcher. Saving hot-reloads the running fetcher, no backend restart needed."
        actions={
          <>
            {savedNotice && (
              <span
                role="status"
                className={clsx(
                  "text-[length:var(--fs-12)]",
                  savedNotice === "Save failed" ? "text-loss" : "text-text-2",
                )}
              >
                {savedNotice}
              </span>
            )}
            {dirty && (
              <button
                type="button"
                onClick={reset}
                className="h-8 rounded-md border border-border-subtle bg-bg-1 px-3 text-[length:var(--fs-13)] font-medium text-text-2 transition-colors hover:bg-bg-2 hover:text-text-1"
              >
                Reset
              </button>
            )}
            <button
              type="button"
              onClick={save}
              disabled={!dirty || saving}
              className={clsx(
                "inline-flex h-8 items-center gap-1.5 rounded-md px-4 text-[length:var(--fs-13)] font-semibold transition-colors",
                dirty
                  ? "bg-text-1 text-bg-0 hover:opacity-90"
                  : "cursor-default border border-border-subtle text-text-3",
                saving && "cursor-wait opacity-60",
              )}
              title={
                dirty
                  ? "Persist your changes to the backend"
                  : "Nothing to save. Toggle a sport, market, tier, visible book or the liquidity minimum to enable."
              }
            >
              {dirty && !saving && <Save size={13} aria-hidden />}
              {saving ? "Saving…" : dirty ? "Save changes" : "Nothing to save"}
            </button>
            <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
          </>
        }
      />

      <div className="flex flex-col gap-4">
        {error && <BackendUnreachable error={error} />}
        {isLoading && !data && <div className="skeleton h-24 rounded-lg" aria-label="Loading settings" />}

        <Panel title="Data sources">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border-subtle px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="text-[length:var(--fs-14)] font-medium text-text-1">Coral33</div>
              <div className="text-[length:var(--fs-12)] text-text-3">
                Run a refresh cycle now across every configured sport: main lines first, then alternates and props.
              </div>
            </div>
            <Coral33RefreshButton />
          </div>
          <Link
            href="/settings/mapping-health"
            className="group flex items-center gap-6 px-4 py-3 transition-colors hover:bg-bg-2"
          >
            <div className="min-w-0 flex-1">
              <div className="text-[length:var(--fs-14)] font-medium text-text-1">Mapping health</div>
              <div className="text-[length:var(--fs-12)] text-text-3">
                Team, player and market names the matcher couldn&rsquo;t resolve.
              </div>
            </div>
            <ChevronRight size={16} aria-hidden className="text-text-3 group-hover:text-text-1" />
          </Link>
        </Panel>

        {/* Density writes html[data-density] so the --row-* vars cascade to
            every table. Persisted in localStorage (density_v1). */}
        <Panel title="Display">
          <div className="px-4 py-3">
            <DensityToggle />
          </div>
        </Panel>

        <Panel title="Edges">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
            <div className="min-w-0 flex-1">
              <label
                htmlFor="min-liquidity"
                className="text-[length:var(--fs-14)] font-medium text-text-1"
              >
                Minimum liquidity
              </label>
              <div className="text-[length:var(--fs-12)] text-text-3">
                Hide Kalshi and Polymarket US prices with less than this much available at the shown price.
                Arbs fall back to the next book with enough depth. Sportsbooks are never filtered. 0 turns it off.
              </div>
            </div>
            <div className="flex h-8 items-center rounded-md border border-border-subtle bg-bg-1 px-2 focus-within:border-text-3">
              <span className="text-[length:var(--fs-13)] text-text-3">$</span>
              <input
                id="min-liquidity"
                type="number"
                inputMode="numeric"
                min={0}
                step={25}
                value={minLiquidity}
                onChange={e => {
                  const n = Math.round(Number(e.target.value));
                  setMinLiquidity(Number.isFinite(n) && n > 0 ? Math.min(n, 1_000_000) : 0);
                }}
                className="tabular w-24 bg-transparent px-1 text-right text-[length:var(--fs-13)] text-text-1 outline-none"
              />
            </div>
          </div>
        </Panel>

        <BookVisibilitySettings value={visibleBooks} onChange={setVisibleBooks} />

        {data && (
          <Panel title="Sports and markets">
            <ul>
              {data.sports.map((sport: SportOption) => {
                const sportOn = !disabledSports.has(sport.key);
                const isExpanded = expanded.has(sport.key);
                return (
                  <li key={sport.key} className="border-b border-border-subtle last:border-b-0">
                    <div className="flex items-center gap-3 px-4 py-2.5">
                      <button
                        type="button"
                        onClick={() => toggleSport(sport.key)}
                        className="flex-shrink-0 cursor-pointer"
                        aria-label={`${sportOn ? "Disable" : "Enable"} ${sport.label}`}
                      >
                        <TriCheckbox state={sportOn ? "on" : "off"} />
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleExpanded(sport.key)}
                        aria-expanded={isExpanded}
                        className="flex min-w-0 flex-1 items-center gap-3 text-left"
                      >
                        <span className={clsx("text-[length:var(--fs-14)] font-semibold", sportOn ? "text-text-1" : "text-text-3")}>
                          {sport.label}
                        </span>
                        <span className="text-[length:var(--fs-12)] text-text-3">
                          <span className="tabular">{sport.tiers.length}</span> {sport.tiers.length === 1 ? "tier" : "tiers"},{" "}
                          <span className="tabular">{marketCount(sport)}</span> markets
                        </span>
                        <ChevronDown
                          size={14}
                          aria-hidden
                          className={clsx("ml-auto text-text-3 transition-transform", isExpanded && "rotate-180")}
                        />
                      </button>
                    </div>
                    {isExpanded && (
                      <div
                        className={clsx(
                          "flex flex-col border-t border-border-subtle bg-bg-0/40",
                          !sportOn && "opacity-50",
                        )}
                      >
                        {sport.tiers.map((tier: TierOption) => {
                          const state = tierState(sport, tier.name);
                          return (
                            <div key={tier.name} className="border-b border-border-subtle px-4 py-3 last:border-b-0">
                              <div className="flex items-center gap-3 pl-7">
                                <button
                                  type="button"
                                  onClick={() => setTierState(sport, tier.name, state !== "on")}
                                  className="flex-shrink-0 cursor-pointer"
                                  aria-label={`Toggle ${tier.name}`}
                                >
                                  <TriCheckbox state={state} />
                                </button>
                                <span className="text-[length:var(--fs-13)] font-semibold text-text-1">
                                  {tierLabel(tier.name, sport.key)}
                                </span>
                                <span className="text-[length:var(--fs-12)] text-text-3">
                                  every <span className="tabular">{tier.interval_seconds}s</span>
                                </span>
                                {!tier.enabled_in_config && <Chip tone="stale">Off in config</Chip>}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 pl-14">
                                {tier.markets.map((market: MarketOption) => {
                                  const disabled = disabledMarkets[sport.key]?.has(market.key) ?? false;
                                  return (
                                    <button
                                      type="button"
                                      key={market.key}
                                      onClick={() => toggleMarket(sport.key, market.key)}
                                      className={clsx(
                                        "inline-flex items-center gap-2 py-1 text-[length:var(--fs-12)] transition-colors",
                                        disabled ? "text-text-3" : "text-text-2 hover:text-text-1",
                                      )}
                                    >
                                      <TriCheckbox state={disabled ? "off" : "on"} />
                                      <span>{formatMarketKey(market.key)}</span>
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}
