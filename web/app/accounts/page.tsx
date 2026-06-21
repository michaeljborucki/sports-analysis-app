"use client";
import Link from "next/link";
import useSWR from "swr";
import clsx from "clsx";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Wallet,
} from "lucide-react";

import { fetchJson } from "@/lib/api";
import { FreshnessChip } from "@/components/freshness-chip";
import { EmptyState } from "@/components/empty-state";
import { useEffect, useMemo, useState } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

interface WagerSummary {
  open_count: number;
  open_amount_risked: number;
  open_amount_to_win: number;
  straight_count: number;
  parlay_count: number;
  parlay_partial_count: number;
  free_play_count: number;
}

interface WagerLeg {
  play_number: number;
  description: string;
  sport_type: string | null;
  sport_sub_type: string | null;
  period: string | null;
  team1: string | null;
  team2: string | null;
  chosen_team: string | null;
  final_money: number | null;
  spread: number | null;
  total_points: number | null;
  game_datetime: string | null;
  outcome: string | null;
  leg_amount_wagered: number;
  leg_to_win_amount: number;
}

interface PendingWager {
  ticket_number: number;
  wager_number: number;
  bet_type: string;
  wager_status: string | null;
  amount_wagered: number;
  to_win_amount: number;
  is_free_play: boolean;
  accepted_at: string | null;
  parlay_name: string | null;
  teaser_name: string | null;
  legs: WagerLeg[];
  has_open_legs: boolean;
  has_graded_legs: boolean;
  is_partial: boolean;
}

interface AccountSnapshot {
  customer_id: string;
  label: string;
  fetched_at: string;
  current_balance: number;
  available_balance: number;
  pending_wager_balance: number;
  free_play_balance: number;
  credit_limit: number;
  wager_limit: number;
  player_name: string | null;
  agent_id: string | null;
  wagers: WagerSummary;
  pending_wagers: PendingWager[];
  error: string | null;
}

interface AccountsRollup {
  snapshots: AccountSnapshot[];
  refreshed_at: string | null;
  refreshing: boolean;
  total_current_balance: number;
  total_available_balance: number;
  total_pending_balance: number;
  total_free_play: number;
  total_open_wagers: number;
  account_count: number;
}

interface HistoryPoint {
  date: string;
  won: number;
  lost: number;
  net: number;
  balance: number;
  /** Open-wager $ at end of day. 0 for historical days (Coral33 doesn't
   * carry this); the latest point is populated from the live snapshot. */
  pending: number;
}

interface AccountHistory {
  customer_id: string;
  label: string;
  points: HistoryPoint[];
}

interface HistoryRollup {
  weeks: number;
  accounts: AccountHistory[];
}

interface BetEntry {
  customer_id: string;
  account_label: string;
  ticket_number: number;
  accepted_at: string;
  settled_at: string | null;
  wager_status: string;     // 'O' | 'W' | 'L' | 'P' | 'X' | other coral codes
  wager_type: string;       // 'S'|'P'|'T'|'M'|'L'|'E'|'R'|...
  total_picks: number;      // 1 for straight, N for parlay (head leg shown)
  amount_wagered: number;
  to_win_amount: number;
  amount_won: number;
  amount_lost: number;
  is_free_play: boolean;
  sport_type: string | null;
  sport_sub_type: string | null;
  period: string | null;
  team1_id: string | null;
  team2_id: string | null;
  chosen_team_id: string | null;
  description: string | null;
  final_money: number | null;
  adj_spread: number | null;
  adj_total_points: number | null;
  // CLV — null until the closing-line snapshot pipeline is wired.
  clv_pct: number | null;
}

interface BetsResponse {
  bets: BetEntry[];
  total_count: number;
  backfill_weeks: number;
}

type BetsTab = "balance" | "bets";

function fmtUsd(n: number, opts?: { compact?: boolean }): string {
  const sign = n < 0 ? "-" : "";
  if (opts?.compact && Math.abs(n) >= 1000) {
    return `${sign}$${(Math.abs(n) / 1000).toFixed(1)}k`;
  }
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtSignedUsd(n: number): string {
  const sign = n < 0 ? "-" : "+";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtAge(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.round(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function fmtAmericanOdds(n: number | null): string {
  if (n == null) return "—";
  return n > 0 ? `+${n}` : `${n}`;
}

function fmtAcceptedAt(iso: string | null): string {
  if (!iso) return "—";
  // coral33 hands back e.g. "2026-04-19 18:42:11.000". Trim ms + show local.
  const cleaned = iso.replace(" ", "T").split(".")[0] + "Z";
  const d = new Date(cleaned);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function AccountsPage() {
  const { data, mutate, isValidating } = useSWR<AccountsRollup>(
    "/api/coral33/accounts",
    fetchJson,
    { refreshInterval: 30_000 },
  );
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<BetsTab>("balance");

  const { data: history } = useSWR<HistoryRollup>(
    "/api/coral33/accounts/history?weeks=12",
    fetchJson,
    { refreshInterval: 5 * 60_000 },
  );

  // Bets fetch is gated on the tab — switching to Bets triggers the
  // initial load; switching away pauses revalidation. The endpoint is
  // cheap (reads from the persisted wager-log JSONs), but there's no
  // need to poll it when the tab isn't visible.
  const { data: betsData } = useSWR<BetsResponse>(
    tab === "bets" ? "/api/coral33/accounts/bets" : null,
    fetchJson,
    { refreshInterval: 5 * 60_000 },
  );

  function toggleExpanded(customerId: string) {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(customerId)) next.delete(customerId);
      else next.add(customerId);
      return next;
    });
  }

  async function refresh() {
    if (busy) return;
    setBusy(true);
    try {
      await fetch(`${API_BASE}/api/coral33/accounts/refresh`, {
        method: "POST",
      }).catch(() => {});
      // Server scrape takes ~1-2s per account. Poll for `refreshing=false`.
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 750));
        const fresh = await mutate();
        if (fresh && !fresh.refreshing) break;
      }
    } finally {
      setBusy(false);
    }
  }

  const refreshing = busy || data?.refreshing === true;

  // Auto-trigger a refresh on first mount when the in-memory cache is empty
  // but credentials are configured. The accounts scraper holds state in
  // process and gets wiped on every backend restart, so without this the
  // page renders blank (account_count > 0, snapshots = []) until the user
  // remembers to click Refresh.
  const [autoRefreshTried, setAutoRefreshTried] = useState(false);
  useEffect(() => {
    if (autoRefreshTried) return;
    if (!data) return;  // wait for first SWR fetch
    if (data.account_count > 0 && data.snapshots.length === 0 && !data.refreshing) {
      setAutoRefreshTried(true);
      void refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, autoRefreshTried]);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-[28px] leading-[30px] font-semibold tracking-tight text-text-1">
            Accounts
          </h1>
          <span className="text-xs text-text-3 tabular hidden sm:inline">
            coral33 multi-account roll-up
          </span>
          {data?.refreshed_at && (
            <span className="text-xs text-text-3 tabular">
              refreshed {fmtAge(data.refreshed_at)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <FreshnessChip />
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className={clsx(
              "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
              "bg-bg-1 border border-border-subtle text-text-2 hover:text-text-1",
              "transition-colors disabled:cursor-not-allowed disabled:opacity-70",
            )}
          >
            <RefreshCw
              size={12}
              aria-hidden
              className={clsx("transition-transform", refreshing && "animate-spin")}
            />
            <span>{refreshing ? "Refreshing…" : "Refresh"}</span>
          </button>
        </div>
      </header>

      {data && data.account_count === 0 && (
        <EmptyState
          title="No coral33 accounts configured"
          body="Set the CORAL33_ACCOUNTS environment variable as a JSON list of {customer_id, password, label} to enable the multi-account roll-up. Falls back to CORAL33_CUSTOMER_ID + CORAL33_PASSWORD for a single account."
          icon={<Wallet aria-hidden />}
        />
      )}

      {data &&
        data.account_count > 0 &&
        data.snapshots.length === 0 && (
          <div className="text-text-2 text-sm">
            {refreshing
              ? `Scraping ${data.account_count} coral33 account${data.account_count === 1 ? "" : "s"}…`
              : "No cached account data — pulling now."}
          </div>
        )}

      {data && data.snapshots.length > 0 && (
        <>
          {/* Roll-up tiles */}
          <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <RollupTile
              label="Total balance"
              value={fmtUsd(data.total_current_balance)}
              tone={data.total_current_balance >= 0 ? "neutral" : "warning"}
              sub={`${data.snapshots.filter(s => !s.error).length} of ${data.account_count} accounts`}
            />
            <RollupTile
              label="Available"
              value={fmtUsd(data.total_available_balance)}
            />
            <RollupTile
              label="Pending"
              value={fmtUsd(data.total_pending_balance)}
              sub={`${data.total_open_wagers} open wager${data.total_open_wagers === 1 ? "" : "s"}`}
            />
            <RollupTile
              label="Free play"
              value={fmtUsd(data.total_free_play)}
              tone={data.total_free_play > 0 ? "positive" : "neutral"}
            />
          </section>

          {/* Sub-tab nav: Balance (chart + per-account table) vs Bets
              (flat ticket history across all accounts). State is local
              to the page — switching tabs doesn't change the URL since
              the same data populates both views from the same wager-log
              cache. */}
          <div
            role="tablist"
            aria-label="Accounts view"
            className="inline-flex h-8 rounded-md border border-border-subtle bg-bg-1 p-0.5 text-[11px] font-medium uppercase tracking-wider"
          >
            <ChartModeButton
              active={tab === "balance"}
              onClick={() => setTab("balance")}
              label="Balance"
            />
            <ChartModeButton
              active={tab === "bets"}
              onClick={() => setTab("bets")}
              label={`Bets${
                betsData?.total_count ? ` · ${betsData.total_count}` : ""
              }`}
            />
          </div>

          {tab === "bets" ? (
            <div className="rounded border border-border-subtle bg-bg-1 p-6 flex items-center justify-between">
              <div className="text-sm text-text-2">
                Bet history moved to the new{" "}
                <Link href="/bets" className="text-accent underline">
                  /bets
                </Link>{" "}
                page — it now includes Kalshi, Polymarket, and CSV imports
                alongside Coral33.
              </div>
              <Link
                href="/bets"
                className="rounded border border-border-subtle bg-bg-2 px-3 py-1.5 text-sm"
              >
                View bets →
              </Link>
            </div>
          ) : (
            <>

          {/* Cumulative P&L chart */}
          {history && history.accounts.length > 0 && (
            <PnLChart history={history} />
          )}

          {/* Per-account table */}
          <section className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-bg-1 text-text-2">
                <tr>
                  <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px] w-[28px]"></th>
                  <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Account
                  </th>
                  <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Balance
                  </th>
                  <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Available
                  </th>
                  <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Pending
                  </th>
                  <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Free play
                  </th>
                  <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                    Open bets
                  </th>
                  <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[180px]">
                    Bet mix
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.snapshots.map(s => (
                  <AccountRow
                    key={s.customer_id}
                    snap={s}
                    isExpanded={expanded.has(s.customer_id)}
                    onToggle={() => toggleExpanded(s.customer_id)}
                  />
                ))}
              </tbody>
            </table>
          </section>
            </>
          )}
        </>
      )}
    </div>
  );
}


function RollupTile({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "positive" | "warning";
}) {
  return (
    <div className="border border-border-subtle rounded-md bg-bg-1 px-4 py-3 flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-text-3">
        {label}
      </span>
      <span
        className={clsx(
          "text-[20px] font-semibold tabular",
          tone === "positive" && "text-price-up",
          tone === "warning" && "text-price-down",
          tone === "neutral" && "text-text-1",
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[11px] text-text-3 tabular">{sub}</span>}
    </div>
  );
}


function AccountRow({
  snap,
  isExpanded,
  onToggle,
}: {
  snap: AccountSnapshot;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const w = snap.wagers;
  const display = snap.player_name || snap.label || snap.customer_id;
  const hasDetail = snap.pending_wagers.length > 0 || snap.wager_limit > 0;
  return (
    <>
      <tr
        className={clsx(
          "border-t border-border-subtle hover:bg-bg-1/40 cursor-pointer",
          isExpanded && "bg-bg-1/40",
        )}
        onClick={hasDetail ? onToggle : undefined}
      >
        <td className="px-2 py-2 align-top">
          {hasDetail ? (
            isExpanded ? (
              <ChevronDown size={14} className="text-text-3" aria-hidden />
            ) : (
              <ChevronRight size={14} className="text-text-3" aria-hidden />
            )
          ) : null}
        </td>
        <td className="px-2 py-2 align-top">
          <div className="flex flex-col gap-0.5">
            <span className="text-text-1 font-medium">{display}</span>
            <span className="text-text-3 text-[10px] tabular">
              {snap.customer_id}
              {snap.agent_id && ` · agent ${snap.agent_id}`}
            </span>
            {snap.error && (
              <span className="inline-flex items-center gap-1 text-[10px] text-price-down mt-1">
                <AlertCircle size={10} aria-hidden />
                {snap.error}
              </span>
            )}
          </div>
        </td>
        <td className={clsx(
          "px-2 py-2 text-right tabular align-top",
          snap.current_balance < 0 && "text-price-down",
          snap.current_balance > 0 && "text-text-1",
        )}>
          {fmtUsd(snap.current_balance)}
        </td>
        <td className="px-2 py-2 text-right tabular text-text-1 align-top">
          {fmtUsd(snap.available_balance)}
        </td>
        <td className="px-2 py-2 text-right tabular text-text-2 align-top">
          {fmtUsd(snap.pending_wager_balance)}
        </td>
        <td className={clsx(
          "px-2 py-2 text-right tabular align-top",
          snap.free_play_balance > 0 ? "text-price-up" : "text-text-3",
        )}>
          {fmtUsd(snap.free_play_balance)}
        </td>
        <td className="px-2 py-2 text-right tabular align-top">
          <span className={clsx(
            "text-text-1 font-medium",
            w.open_count === 0 && "text-text-3",
          )}>
            {w.open_count}
          </span>
          {w.open_count > 0 && (
            <span className="text-text-3 text-[10px] block tabular">
              risk {fmtUsd(w.open_amount_risked)}
            </span>
          )}
        </td>
        <td className="px-2 py-2 align-top">
          {w.open_count === 0 ? (
            <span className="text-text-3 text-[10px]">—</span>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {w.straight_count > 0 && (
                <BetMixChip label="Straight" count={w.straight_count} tone="neutral" />
              )}
              {w.parlay_count > 0 && (
                <BetMixChip label="Parlay" count={w.parlay_count} tone="accent" />
              )}
              {w.parlay_partial_count > 0 && (
                <BetMixChip
                  label="Partial"
                  count={w.parlay_partial_count}
                  tone="warning"
                  title="Parlays where some legs are graded but others still open"
                />
              )}
              {w.free_play_count > 0 && (
                <BetMixChip label="Free Play" count={w.free_play_count} tone="positive" />
              )}
            </div>
          )}
        </td>
      </tr>
      {isExpanded && (
        <tr className="border-t border-border-subtle bg-bg-1/20">
          <td colSpan={8} className="px-3 py-3">
            <ExpandedDetail snap={snap} />
          </td>
        </tr>
      )}
    </>
  );
}


function ExpandedDetail({ snap }: { snap: AccountSnapshot }) {
  const creditUsed =
    snap.current_balance < 0 ? Math.abs(snap.current_balance) : 0;
  const creditPct =
    snap.credit_limit > 0
      ? Math.min(100, (creditUsed / snap.credit_limit) * 100)
      : 0;
  const wagerPct =
    snap.wager_limit > 0
      ? Math.min(100, (snap.pending_wager_balance / snap.wager_limit) * 100)
      : 0;

  return (
    <div className="flex flex-col gap-4">
      {/* Limit utilization bars */}
      {(snap.credit_limit > 0 || snap.wager_limit > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {snap.credit_limit > 0 && (
            <UtilizationBar
              label="Credit utilization"
              used={creditUsed}
              limit={snap.credit_limit}
              pct={creditPct}
              tone={creditPct > 80 ? "warning" : creditPct > 50 ? "caution" : "neutral"}
            />
          )}
          {snap.wager_limit > 0 && (
            <UtilizationBar
              label="Wager limit"
              used={snap.pending_wager_balance}
              limit={snap.wager_limit}
              pct={wagerPct}
              tone={wagerPct > 80 ? "warning" : wagerPct > 50 ? "caution" : "neutral"}
            />
          )}
        </div>
      )}

      {/* Pending wagers */}
      {snap.pending_wagers.length === 0 ? (
        <div className="text-text-3 text-[11px]">No open wagers</div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-[10px] uppercase tracking-wider text-text-3">
            Open wagers ({snap.pending_wagers.length})
          </div>
          <div className="flex flex-col gap-1.5">
            {snap.pending_wagers.map(w => (
              <WagerCard key={`${w.ticket_number}-${w.wager_number}`} wager={w} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function UtilizationBar({
  label,
  used,
  limit,
  pct,
  tone,
}: {
  label: string;
  used: number;
  limit: number;
  pct: number;
  tone: "neutral" | "caution" | "warning";
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-text-3 uppercase tracking-wider text-[10px]">
          {label}
        </span>
        <span className="text-text-2 tabular">
          {fmtUsd(used)} / {fmtUsd(limit)}
          <span className="text-text-3 ml-1.5">{pct.toFixed(0)}%</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-bg-0 border border-border-subtle overflow-hidden">
        <div
          className={clsx(
            "h-full transition-all",
            tone === "warning" && "bg-price-down",
            tone === "caution" && "bg-flash",
            tone === "neutral" && "bg-accent",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}


function WagerCard({ wager }: { wager: PendingWager }) {
  const isParlay = wager.legs.length > 1;
  const title =
    wager.parlay_name ||
    wager.teaser_name ||
    (isParlay ? `${wager.legs.length}-leg ${wager.bet_type}` : wager.bet_type);

  return (
    <div className="border border-border-subtle rounded-md bg-bg-0 p-2.5 flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-text-1 text-[11px] font-medium capitalize">
            {title}
          </span>
          {wager.is_partial && (
            <span className="inline-flex items-center px-1.5 h-4 rounded-sm bg-flash/15 border border-flash/40 text-flash text-[9px] font-medium uppercase">
              Partial
            </span>
          )}
          {wager.is_free_play && (
            <span className="inline-flex items-center px-1.5 h-4 rounded-sm bg-price-up/15 border border-price-up/40 text-price-up text-[9px] font-medium uppercase">
              Free Play
            </span>
          )}
          <span className="text-text-3 text-[10px] tabular">
            #{wager.ticket_number}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] tabular">
          <span className="text-text-3">
            risk <span className="text-text-1">{fmtUsd(wager.amount_wagered)}</span>
          </span>
          <span className="text-text-3">
            win <span className="text-text-1">{fmtUsd(wager.to_win_amount)}</span>
          </span>
          <span className="text-text-3 hidden sm:inline">
            {fmtAcceptedAt(wager.accepted_at)}
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-1 pl-1">
        {wager.legs.map((leg, i) => (
          <LegRow key={`${i}-${leg.play_number}`} leg={leg} />
        ))}
      </div>
    </div>
  );
}


function LegRow({ leg }: { leg: WagerLeg }) {
  const lineLabel = (() => {
    if (leg.spread != null && leg.spread !== 0) {
      const s = leg.spread > 0 ? `+${leg.spread}` : `${leg.spread}`;
      return s;
    }
    if (leg.total_points != null && leg.total_points !== 0) {
      return `o/u ${leg.total_points}`;
    }
    return null;
  })();

  const matchup =
    leg.team1 && leg.team2 ? `${leg.team1} @ ${leg.team2}` : null;

  return (
    <div className="flex items-start justify-between gap-3 py-1 border-t border-border-subtle/50 first:border-t-0 first:pt-0">
      <div className="flex flex-col gap-0.5 min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <LegStatusDot outcome={leg.outcome} />
          <span className="text-text-1 text-[11px] font-medium">
            {leg.chosen_team || leg.description.split(" ")[0]}
          </span>
          {lineLabel && (
            <span className="text-text-2 text-[11px] tabular">{lineLabel}</span>
          )}
          <span className="text-text-3 text-[11px] tabular">
            {fmtAmericanOdds(leg.final_money)}
          </span>
          {leg.period && leg.period !== "Game" && (
            <span className="text-text-3 text-[10px] uppercase tracking-wider">
              {leg.period}
            </span>
          )}
        </div>
        {matchup && (
          <span className="text-text-3 text-[10px] truncate">
            {matchup}
            {leg.sport_sub_type && ` · ${leg.sport_sub_type}`}
          </span>
        )}
      </div>
    </div>
  );
}


function LegStatusDot({ outcome }: { outcome: string | null }) {
  const tone =
    outcome === "won"
      ? "bg-price-up"
      : outcome === "lost"
        ? "bg-price-down"
        : outcome === "push"
          ? "bg-text-3"
          : "bg-accent";
  const title =
    outcome === "won"
      ? "Won"
      : outcome === "lost"
        ? "Lost"
        : outcome === "push"
          ? "Push"
          : "Open";
  return (
    <span
      title={title}
      className={clsx("inline-block w-1.5 h-1.5 rounded-full", tone)}
    />
  );
}


function BetMixChip({
  label,
  count,
  tone,
  title,
}: {
  label: string;
  count: number;
  tone: "neutral" | "accent" | "positive" | "warning";
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 px-1.5 h-5 rounded-sm border text-[10px] font-medium tabular",
        tone === "neutral" && "bg-bg-1 border-border-subtle text-text-2",
        tone === "accent" && "bg-accent/10 border-accent/40 text-accent",
        tone === "positive" && "bg-price-up/10 border-price-up/40 text-price-up",
        tone === "warning" && "bg-flash/10 border-flash/40 text-flash",
      )}
    >
      <span>{label}</span>
      <span>{count}</span>
    </span>
  );
}


// ─── Cumulative P&L chart ─────────────────────────────────────────────────

const CHART_COLORS = [
  "var(--color-accent)",
  "var(--color-price-up)",
  "var(--color-flash)",
  "var(--color-price-down)",
  "#a78bfa", // violet-400 fallback
  "#60a5fa", // blue-400 fallback
];

type ChartMode = "total" | "split";

interface ChartSeries {
  customer_id: string;
  label: string;
  color: string;
  points: HistoryPoint[];
}

function PnLChart({ history }: { history: HistoryRollup }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [mode, setMode] = useState<ChartMode>("total");

  const accountSeries = useMemo<ChartSeries[]>(() => {
    return history.accounts
      .filter(a => a.points.length > 0)
      .map((a, i) => ({
        customer_id: a.customer_id,
        label: a.label,
        color: CHART_COLORS[i % CHART_COLORS.length],
        points: a.points,
      }));
  }, [history]);

  // Combined-total series: at each timestep, sum balance and net across
  // every account. Built once regardless of mode so the toggle is a no-op
  // re-render rather than a recompute.
  const totalSeries = useMemo<ChartSeries | null>(() => {
    if (accountSeries.length === 0) return null;
    const numPoints = accountSeries[0].points.length;
    const totalPoints: HistoryPoint[] = [];
    for (let i = 0; i < numPoints; i++) {
      let balance = 0;
      let net = 0;
      let pending = 0;
      let date = "";
      for (const s of accountSeries) {
        const p = s.points[i];
        if (!p) continue;
        balance += p.balance;
        net += p.net;
        pending += p.pending;
        if (!date) date = p.date;
      }
      totalPoints.push({
        date,
        won: 0,
        lost: 0,
        net,
        balance,
        pending,
      });
    }
    return {
      customer_id: "__total__",
      label: "All accounts",
      color: "var(--color-accent)",
      points: totalPoints,
    };
  }, [accountSeries]);

  if (accountSeries.length === 0 || !totalSeries) return null;

  const series: ChartSeries[] = mode === "total" ? [totalSeries] : accountSeries;

  const numPoints = series[0].points.length;
  // Y-range needs headroom for the pending segment that stacks on top of
  // the balance bar in total mode. Use balance+pending for the max so the
  // chart doesn't clip the pending cap.
  const allValues = series.flatMap(s =>
    s.points.flatMap(p => [p.balance, p.balance + p.pending]),
  );
  const minY = Math.min(0, ...allValues);
  const maxY = Math.max(0, ...allValues);
  const padY = (maxY - minY) * 0.1 || 100;
  const yLo = minY - padY;
  const yHi = maxY + padY;

  const startBalance = totalSeries.points[0]?.balance ?? 0;
  const endBalance =
    totalSeries.points[totalSeries.points.length - 1]?.balance ?? 0;
  const totalChange = endBalance - startBalance;

  // SVG layout
  const W = 800;
  const H = 200;
  const padL = 56;
  const padR = 16;
  const padT = 12;
  const padB = 28;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  // Line mode (split) needs fence-post positioning so the polyline spans
  // the inner-area corners exactly. Bar mode (total) needs slot-centered
  // positioning so each day owns an equal-width column inside innerW with
  // no half-cut bars at the left/right edges. Hover detection mirrors
  // each mode's positioning so the cursor's bar matches the readout.
  const xAtLine = (i: number) =>
    padL + (numPoints <= 1 ? innerW / 2 : (i / (numPoints - 1)) * innerW);
  const slotW = numPoints > 0 ? innerW / numPoints : innerW;
  const xAtBar = (i: number) =>
    padL + (i + 0.5) * slotW;
  // Unified accessor — bar mode uses slot centers, line mode uses fence
  // posts. Used by the hover crosshair + the X-axis labels so they align
  // with whatever's actually rendered.
  const xAt = mode === "total" ? xAtBar : xAtLine;
  const yAt = (v: number) =>
    padT + ((yHi - v) / (yHi - yLo)) * innerH;

  // Y-axis ticks: 4 evenly spaced
  const yTicks = [0, 1, 2, 3, 4].map(t => yLo + ((yHi - yLo) * t) / 4);

  // Hover crosshair
  const hoverX = hoverIdx != null ? xAt(hoverIdx) : null;

  return (
    <section className="border border-border-subtle rounded-md bg-bg-0 p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3">
          <span className="text-[10px] uppercase tracking-wider text-text-3">
            Daily balance · {history.weeks}w
          </span>
          <span className="text-[15px] font-semibold tabular text-text-1">
            {fmtUsd(endBalance)}
          </span>
          <span
            className={clsx(
              "text-[11px] tabular",
              totalChange > 0 && "text-price-up",
              totalChange < 0 && "text-price-down",
              totalChange === 0 && "text-text-3",
            )}
          >
            {fmtSignedUsd(totalChange)}
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {mode === "total" && (
            <div className="flex flex-wrap gap-2.5 text-[11px] text-text-2">
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block w-2 h-2"
                  style={{ background: "var(--color-accent)", opacity: 0.85 }}
                />
                <span>Cleared</span>
                <span className="tabular text-text-3">{fmtUsd(endBalance)}</span>
              </span>
              {(() => {
                const lastPoint = totalSeries.points[totalSeries.points.length - 1];
                const pending = lastPoint?.pending ?? 0;
                if (pending <= 0) return null;
                return (
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="inline-block w-2 h-2"
                      style={{ background: "var(--color-flash)", opacity: 0.7 }}
                    />
                    <span>Pending</span>
                    <span className="tabular text-text-3">{fmtUsd(pending)}</span>
                  </span>
                );
              })()}
            </div>
          )}
          {mode === "split" && (
            <div className="flex flex-wrap gap-2.5">
              {accountSeries.map(s => (
                <span
                  key={s.customer_id}
                  className="inline-flex items-center gap-1.5 text-[11px] text-text-2"
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full"
                    style={{ background: s.color }}
                  />
                  <span>{s.label}</span>
                  <span className="tabular text-text-3">
                    {fmtUsd(
                      s.points[s.points.length - 1]?.balance ?? 0,
                    )}
                  </span>
                </span>
              ))}
            </div>
          )}
          <div
            role="tablist"
            aria-label="Chart aggregation"
            className="inline-flex h-6 rounded-md border border-border-subtle bg-bg-1 p-0.5 text-[10px] font-medium uppercase tracking-wider"
          >
            <ChartModeButton
              active={mode === "total"}
              onClick={() => setMode("total")}
              label="Total"
            />
            <ChartModeButton
              active={mode === "split"}
              onClick={() => setMode("split")}
              label="Per account"
            />
          </div>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-[200px]"
        onMouseLeave={() => setHoverIdx(null)}
        onMouseMove={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = ((e.clientX - rect.left) / rect.width) * W;
          if (x < padL || x > W - padR) {
            setHoverIdx(null);
            return;
          }
          // Bar mode is slot-based — divide the inner width into N slots
          // and the cursor's slot is its index. floor() gives the slot
          // containing the cursor; clamping covers the right-edge case
          // where x == padL + innerW falls into a non-existent slot N.
          //
          // Line mode is fence-post — the cursor's nearest data point is
          // the one whose xAtLine(i) is closest to x, which is what
          // round(t * (N-1)) gives.
          const t = (x - padL) / innerW;
          const idx =
            mode === "total"
              ? Math.floor(t * numPoints)
              : Math.round(t * (numPoints - 1));
          setHoverIdx(Math.max(0, Math.min(numPoints - 1, idx)));
        }}
      >
        {/* Y-axis grid + labels */}
        {yTicks.map((tv, i) => (
          <g key={i}>
            <line
              x1={padL}
              x2={W - padR}
              y1={yAt(tv)}
              y2={yAt(tv)}
              stroke="var(--color-border-subtle)"
              strokeDasharray={tv === 0 ? "0" : "2 3"}
              strokeWidth={tv === 0 ? 1 : 0.5}
            />
            <text
              x={padL - 6}
              y={yAt(tv) + 3}
              textAnchor="end"
              className="text-text-3 tabular"
              fontSize="10"
              fill="currentColor"
            >
              {fmtUsd(tv, { compact: true })}
            </text>
          </g>
        ))}

        {/* X-axis labels — first, middle, last */}
        {[0, Math.floor(numPoints / 2), numPoints - 1].map(i => {
          const p = series[0].points[i];
          if (!p) return null;
          return (
            <text
              key={i}
              x={xAt(i)}
              y={H - 8}
              textAnchor="middle"
              className="text-text-3 tabular"
              fontSize="10"
              fill="currentColor"
            >
              {p.date.slice(5)}
            </text>
          );
        })}

        {/* Bars (total mode) or lines (split mode).
            Total mode renders ONE stacked bar per day: a solid balance
            segment + a striped pending cap on top. Pending only has data
            on the latest point today — older bars omit the cap.
            Split mode keeps the existing thin-line per-account view since
            stacking 8 accounts × 84 days into bars produces sub-pixel
            widths and a busy frame. */}
        {mode === "total" ? (
          (() => {
            const s = series[0];
            const barW = Math.max(
              1.5,
              numPoints > 1
                ? (innerW / numPoints) * 0.78
                : Math.min(40, innerW * 0.4),
            );
            const yZero = yAt(0);
            return s.points.map((p, i) => {
              const cx = xAt(i);
              const x = cx - barW / 2;
              // Balance bar: stretches from the zero line to the balance
              // value. Handles negative balances by flipping direction.
              const yBal = yAt(p.balance);
              const balTop = Math.min(yBal, yZero);
              const balH = Math.max(0.5, Math.abs(yBal - yZero));
              // Pending stacks above the (positive) balance.
              const yBalPlusPending = yAt(p.balance + p.pending);
              const pendingH = Math.max(0, yBal - yBalPlusPending);
              return (
                <g key={i}>
                  <rect
                    x={x}
                    y={balTop}
                    width={barW}
                    height={balH}
                    fill={s.color}
                    opacity={hoverIdx == null || hoverIdx === i ? 0.85 : 0.55}
                  />
                  {p.pending > 0 && pendingH > 0 && (
                    <rect
                      x={x}
                      y={yBalPlusPending}
                      width={barW}
                      height={pendingH}
                      fill="var(--color-flash)"
                      opacity={hoverIdx == null || hoverIdx === i ? 0.7 : 0.4}
                    >
                      <title>Pending wagers (open bets)</title>
                    </rect>
                  )}
                </g>
              );
            });
          })()
        ) : (
          series.map(s => {
            const d = s.points
              .map((p, i) => `${i === 0 ? "M" : "L"} ${xAt(i)} ${yAt(p.balance)}`)
              .join(" ");
            return (
              <path
                key={s.customer_id}
                d={d}
                fill="none"
                stroke={s.color}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })
        )}

        {/* Hover crosshair. In split mode it's a dashed vertical line +
            a dot on each line. In total mode it's a faint highlight box
            spanning the hovered bar's slot — so the cursor visibly maps
            to a specific bar even when the opacity diff is hard to see
            at 7px bar widths. */}
        {hoverX != null && hoverIdx != null && mode === "total" && (
          <rect
            x={xAtBar(hoverIdx) - slotW / 2}
            y={padT}
            width={slotW}
            height={innerH}
            fill="var(--color-text-1)"
            opacity={0.06}
            pointerEvents="none"
          />
        )}
        {hoverX != null && hoverIdx != null && mode === "split" && (
          <>
            <line
              x1={hoverX}
              x2={hoverX}
              y1={padT}
              y2={H - padB}
              stroke="var(--color-text-3)"
              strokeWidth={0.5}
              strokeDasharray="2 2"
            />
            {series.map(s => {
              const p = s.points[hoverIdx];
              if (!p) return null;
              return (
                <circle
                  key={s.customer_id}
                  cx={hoverX}
                  cy={yAt(p.balance)}
                  r={3}
                  fill={s.color}
                  stroke="var(--color-bg-0)"
                  strokeWidth={1.5}
                />
              );
            })}
          </>
        )}
      </svg>

      {hoverIdx != null && (
        <div className="text-[11px] text-text-2 tabular flex flex-wrap gap-x-4 gap-y-1 px-2">
          <span className="text-text-3">
            {series[0].points[hoverIdx]?.date}
          </span>
          {series.map(s => {
            const p = s.points[hoverIdx];
            if (!p) return null;
            return (
              <span key={s.customer_id} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full"
                  style={{ background: s.color }}
                />
                <span className="text-text-3">{s.label}</span>
                <span
                  className={clsx(
                    p.net > 0 && "text-price-up",
                    p.net < 0 && "text-price-down",
                    p.net === 0 && "text-text-2",
                  )}
                >
                  {fmtSignedUsd(p.net)}
                </span>
                <span className="text-text-3">
                  ({fmtUsd(p.balance)}
                  {p.pending > 0 && (
                    <>
                      {" + "}
                      <span className="text-flash">
                        {fmtUsd(p.pending)} pending
                      </span>
                    </>
                  )}
                  )
                </span>
              </span>
            );
          })}
        </div>
      )}
    </section>
  );
}


function ChartModeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        "px-2 rounded-sm transition-colors",
        active
          ? "bg-bg-0 text-text-1 border border-border-subtle"
          : "text-text-3 hover:text-text-2",
      )}
    >
      {label}
    </button>
  );
}


// ─────────────────────────── Bets table ─────────────────────────────

type BetStatusFilter = "any" | "open" | "settled";

// Map Coral33 wager-status codes → human-readable label + tone. Values
// not in this map render as the raw code (so unexpected statuses still
// surface rather than silently dropping into "settled").
const STATUS_LABEL: Record<string, { label: string; tone: "open" | "win" | "loss" | "push" | "void" }> = {
  O: { label: "Open",   tone: "open" },
  W: { label: "Won",    tone: "win" },
  L: { label: "Lost",   tone: "loss" },
  P: { label: "Push",   tone: "push" },
  X: { label: "Void",   tone: "void" },
};

// Coral33 wager-type codes → display chip. S = straight (no chip; the
// default), everything else gets a small label.
const WAGER_TYPE_LABEL: Record<string, string> = {
  S: "",         // straight — no chip
  M: "",         // money-line single — same as straight visually
  P: "Parlay",
  T: "Teaser",
  R: "RR",       // round-robin
  I: "If-Bet",
  L: "Live",     // observed coral code; treat as live single
  E: "Event",    // observed coral code; treat as event/special
};

function formatBetPick(b: BetEntry): string {
  // Compose the chosen-side + line into one column. Spread bets get the
  // signed point glued to the team; total bets get O/U + the line; ML
  // and miscellany fall back to just the chosen-team or the raw
  // description.
  const team = b.chosen_team_id || b.description || "—";
  if (b.adj_spread != null && b.adj_spread !== 0) {
    const sign = b.adj_spread > 0 ? "+" : "";
    return `${team} ${sign}${b.adj_spread}`;
  }
  if (b.adj_total_points != null && b.adj_total_points !== 0) {
    // Chosen team for totals is often "Over <line>" or "Under <line>" —
    // use the line directly.
    return `${team} ${b.adj_total_points}`;
  }
  return team;
}

function formatBetMatchup(b: BetEntry): string {
  if (!b.team1_id && !b.team2_id) return b.description || "—";
  return `${b.team1_id ?? "?"} @ ${b.team2_id ?? "?"}`;
}

function formatAmericanOdds2(n: number | null): string {
  if (n == null) return "—";
  return n > 0 ? `+${n}` : String(n);
}

function fmtBetDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function BetsTable({
  bets,
  weeks,
}: {
  bets: BetEntry[] | undefined;
  weeks: number | undefined;
}) {
  const [statusFilter, setStatusFilter] = useState<BetStatusFilter>("any");

  // Client-side status filter — the API also supports `?status=`, but
  // filtering in-memory makes toggling instant (no refetch).
  const filtered = useMemo(() => {
    if (!bets) return undefined;
    if (statusFilter === "open")
      return bets.filter(b => b.wager_status === "O");
    if (statusFilter === "settled")
      return bets.filter(b => b.wager_status !== "O");
    return bets;
  }, [bets, statusFilter]);

  if (!bets) {
    return (
      <section className="border border-border-subtle rounded-md bg-bg-0 p-4 text-text-3 text-xs">
        Loading bet history…
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-2">
      {/* Filter row + meta */}
      <div className="flex items-center justify-between gap-3 flex-wrap text-[11px]">
        <div className="flex items-center gap-2">
          <span className="text-text-3 uppercase tracking-wider">Status</span>
          <div
            role="tablist"
            aria-label="Status filter"
            className="inline-flex h-7 rounded-md border border-border-subtle bg-bg-1 p-0.5 font-medium uppercase tracking-wider"
          >
            <ChartModeButton
              active={statusFilter === "any"}
              onClick={() => setStatusFilter("any")}
              label="Any"
            />
            <ChartModeButton
              active={statusFilter === "open"}
              onClick={() => setStatusFilter("open")}
              label="Open"
            />
            <ChartModeButton
              active={statusFilter === "settled"}
              onClick={() => setStatusFilter("settled")}
              label="Settled"
            />
          </div>
        </div>
        <div className="text-text-3 tabular">
          {filtered ? filtered.length : 0} of {bets.length} bets
          {weeks != null && (
            <span className="text-text-3"> · last {weeks}w</span>
          )}
        </div>
      </div>

      <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Placed
              </th>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Account
              </th>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Sport
              </th>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Matchup
              </th>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Bet
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Price
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Stake
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                To Win
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Result
              </th>
              <th
                className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] text-text-3"
                title="Closing-line value — coming soon (requires closing-line snapshots)"
              >
                CLV
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered && filtered.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-3 py-6 text-center text-text-3">
                  No bets match this filter.
                </td>
              </tr>
            ) : (
              filtered?.map(b => (
                <BetRow key={`${b.customer_id}-${b.ticket_number}`} b={b} />
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BetRow({ b }: { b: BetEntry }) {
  const status = STATUS_LABEL[b.wager_status] ?? {
    label: b.wager_status,
    tone: "void" as const,
  };
  const wagerTypeChip =
    WAGER_TYPE_LABEL[b.wager_type] !== undefined
      ? WAGER_TYPE_LABEL[b.wager_type]
      : b.wager_type;
  const showParlayCount = b.total_picks > 1;

  // Net P&L on the result column. Open bets show "—"; pushes show $0;
  // wins show the won amount, losses the negated stake.
  const net = (() => {
    if (b.wager_status === "O") return null;
    if (b.wager_status === "W") return b.amount_won;
    if (b.wager_status === "L") return -b.amount_lost;
    return 0; // push / void
  })();

  return (
    <tr className="border-t border-border-subtle hover:bg-bg-1">
      <td className="px-2 py-1.5 align-middle whitespace-nowrap text-text-2">
        {fmtBetDate(b.accepted_at)}
      </td>
      <td className="px-2 py-1.5 align-middle whitespace-nowrap text-text-1">
        {b.account_label}
      </td>
      <td className="px-2 py-1.5 align-middle whitespace-nowrap text-text-2">
        {b.sport_sub_type ?? b.sport_type ?? "—"}
      </td>
      <td className="px-2 py-1.5 align-middle text-text-2 truncate max-w-[260px]">
        <span title={formatBetMatchup(b)}>{formatBetMatchup(b)}</span>
      </td>
      <td className="px-2 py-1.5 align-middle text-text-1">
        <span className="inline-flex items-center gap-1.5">
          {wagerTypeChip && (
            <span
              className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-accent bg-accent/10"
              title={
                showParlayCount
                  ? `${wagerTypeChip} of ${b.total_picks} legs — head leg shown`
                  : wagerTypeChip
              }
            >
              {wagerTypeChip}
              {showParlayCount ? ` ×${b.total_picks}` : ""}
            </span>
          )}
          {b.is_free_play && (
            <span className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-flash bg-flash/15">
              FREE
            </span>
          )}
          <span>{formatBetPick(b)}</span>
        </span>
      </td>
      <td className="px-2 py-1.5 align-middle text-right tabular text-text-1">
        {formatAmericanOdds2(b.final_money)}
      </td>
      <td className="px-2 py-1.5 align-middle text-right tabular text-text-2">
        {fmtUsd(b.amount_wagered)}
      </td>
      <td className="px-2 py-1.5 align-middle text-right tabular text-text-3">
        {fmtUsd(b.to_win_amount)}
      </td>
      <td className="px-2 py-1.5 align-middle text-right whitespace-nowrap">
        <span
          className={clsx(
            "inline-flex items-center px-1.5 rounded-sm text-[10px] font-semibold tracking-wider",
            status.tone === "open" && "text-text-2 bg-bg-2",
            status.tone === "win" && "text-price-up bg-price-up/15",
            status.tone === "loss" && "text-price-down bg-price-down/15",
            status.tone === "push" && "text-text-2 bg-bg-2",
            status.tone === "void" && "text-text-3 bg-bg-2",
          )}
        >
          {status.label}
        </span>
        {net != null && (
          <span
            className={clsx(
              "tabular ml-1.5",
              net > 0 && "text-price-up",
              net < 0 && "text-price-down",
              net === 0 && "text-text-3",
            )}
          >
            {net > 0 ? "+" : ""}{fmtUsd(Math.abs(net))}
          </span>
        )}
      </td>
      <td
        className="px-2 py-1.5 align-middle text-right tabular text-text-3"
        title="Closing-line value — placeholder until the closing-line snapshot pipeline lands"
      >
        {b.clv_pct == null ? "—" : `${b.clv_pct.toFixed(2)}%`}
      </td>
    </tr>
  );
}
