"use client";
import Link from "next/link";
import useSWR from "swr";
import clsx from "clsx";
import {
  AlertCircle,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Wallet,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { fetchJson } from "@/lib/api";
import { buildTotalHistory } from "@/lib/balance-history";
import { EmptyState } from "@/components/empty-state";
import {
  BackendUnreachable,
  Chip,
  type ChipTone,
  Freshness,
  PageHeader,
  Panel,
  Segmented,
  StatTile,
} from "@/components/ui";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Account balances are scraped on demand; older than this reads as stale. */
const BALANCES_STALE_AFTER_S = 30 * 60;

interface WagerSummary {
  open_count: number;
  open_amount_risked: number;
  open_amount_to_win: number;
  straight_count: number;
  parlay_count: number;
  won_open_slot_count: number;
  pending_open_slot_count: number;
  fulfilled_count: number;
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
  total_side: "over" | "under" | null;
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

/** Wall clock that ticks so the freshness age keeps counting between fetches. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function AccountsPage() {
  const { data, error, mutate } = useSWR<AccountsRollup>(
    "/api/coral33/accounts",
    fetchJson,
    { refreshInterval: 30_000 },
  );
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data: history } = useSWR<HistoryRollup>(
    "/api/coral33/accounts/history?weeks=12",
    fetchJson,
    { refreshInterval: 5 * 60_000 },
  );

  const now = useNow(15_000);
  const refreshedMs = data?.refreshed_at ? Date.parse(data.refreshed_at) : NaN;
  const ageSeconds = Number.isNaN(refreshedMs) ? null : (now - refreshedMs) / 1000;

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
  // A ref, not state: the flag only gates this effect and never renders.
  const autoRefreshTried = useRef(false);
  useEffect(() => {
    if (autoRefreshTried.current) return;
    if (!data) return;  // wait for first SWR fetch
    if (data.account_count > 0 && data.snapshots.length === 0 && !data.refreshing) {
      autoRefreshTried.current = true;
      // Kicking off the async scrape is the point of this effect; refresh()
      // flips `busy` so the button shows progress immediately.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const okCount = data ? data.snapshots.filter(s => !s.error).length : 0;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        className="mb-0"
        title="Accounts"
        description="Coral33 sub-accounts"
        meta={
          <Freshness
            what="Balances"
            ageSeconds={ageSeconds}
            staleAfter={BALANCES_STALE_AFTER_S}
          />
        }
        actions={
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            title="Scrape fresh balances from every Coral33 account"
            className={clsx(
              "inline-flex items-center gap-2 h-8 px-3 rounded-md text-[length:var(--fs-13)] font-medium",
              "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1 hover:bg-bg-2",
              "transition-colors disabled:cursor-wait disabled:opacity-70",
            )}
          >
            <RefreshCw size={13} aria-hidden className={clsx(refreshing && "animate-spin")} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        }
      />

      {error && !data && <BackendUnreachable error={error} />}

      {!data && !error && (
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3" aria-hidden>
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="h-[86px] rounded-lg border border-border-subtle bg-bg-1 animate-pulse" />
          ))}
        </section>
      )}

      {data && data.account_count === 0 && (
        <EmptyState
          title="No Coral33 accounts configured"
          body="Set the CORAL33_ACCOUNTS environment variable as a JSON list of {customer_id, password, label} to enable the multi-account roll-up. Falls back to CORAL33_CUSTOMER_ID + CORAL33_PASSWORD for a single account."
          icon={<Wallet aria-hidden />}
        />
      )}

      {data &&
        data.account_count > 0 &&
        data.snapshots.length === 0 && (
          <div className="rounded-lg border border-border-subtle bg-bg-1 px-4 py-6 text-[length:var(--fs-13)] text-text-2">
            {refreshing ? (
              <>
                Scraping <span className="tabular">{data.account_count}</span> Coral33 account
                {data.account_count === 1 ? "" : "s"}…
              </>
            ) : (
              "No cached account data. Pulling now."
            )}
          </div>
        )}

      {data && data.snapshots.length > 0 && (
        <>
          <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile
              label="Total balance"
              value={fmtUsd(data.total_current_balance)}
              tone={data.total_current_balance < 0 ? "loss" : undefined}
              sub={
                <>
                  <span className="tabular">{okCount}</span> of{" "}
                  <span className="tabular">{data.account_count}</span> accounts
                </>
              }
            />
            <StatTile
              label="Available"
              value={fmtUsd(data.total_available_balance)}
              tone={data.total_available_balance < 0 ? "loss" : undefined}
            />
            <StatTile
              label="Pending"
              value={fmtUsd(data.total_pending_balance)}
              sub={
                <>
                  <span className="tabular">{data.total_open_wagers}</span> open wager
                  {data.total_open_wagers === 1 ? "" : "s"}
                </>
              }
            />
            <StatTile label="Free play" value={fmtUsd(data.total_free_play)} sub="Credit, not cash" />
          </section>

          {history && history.accounts.length > 0 && (
            <PnLChart history={history} />
          )}

          <section className="rounded-lg border border-border-subtle bg-bg-1 overflow-x-auto">
            <table className="w-full">
              <thead className="dt-head">
                <tr>
                  <th className="dt-th w-[36px]"><span className="sr-only">Expand</span></th>
                  <th className="dt-th">Account</th>
                  <th className="dt-th text-right">Balance</th>
                  <th className="dt-th text-right">Available</th>
                  <th className="dt-th text-right">Pending</th>
                  <th className="dt-th text-right">Free play</th>
                  <th className="dt-th text-right">Open bets</th>
                  <th className="dt-th w-[240px]">Bet mix</th>
                </tr>
              </thead>
              <tbody className="bg-bg-0">
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

          <p className="text-[length:var(--fs-13)] text-text-3">
            Bet history, ROI and CLV are on the{" "}
            <Link
              href="/bets"
              className="inline-flex items-center gap-1 font-medium text-text-2 hover:text-text-1 underline-offset-2 hover:underline"
            >
              Bets page
              <ArrowRight size={12} aria-hidden />
            </Link>
          </p>
        </>
      )}
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
          "dt-row",
          hasDetail && "cursor-pointer",
          isExpanded && "bg-bg-2",
        )}
        onClick={hasDetail ? onToggle : undefined}
      >
        <td className="dt-td align-top">
          {hasDetail ? (
            <button
              type="button"
              aria-expanded={isExpanded}
              aria-label={`${isExpanded ? "Collapse" : "Expand"} ${display}`}
              onClick={e => {
                e.stopPropagation();
                onToggle();
              }}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-text-3 hover:text-text-1 hover:bg-bg-2"
            >
              {isExpanded ? (
                <ChevronDown size={14} aria-hidden />
              ) : (
                <ChevronRight size={14} aria-hidden />
              )}
            </button>
          ) : null}
        </td>
        <td className="dt-td align-top">
          <div className="flex flex-col gap-0.5">
            <span className="text-text-1 font-medium">{display}</span>
            <span className="flex flex-wrap gap-x-2 text-[length:var(--fs-11)] text-text-3">
              <span className="tabular">{snap.customer_id}</span>
              {snap.agent_id && (
                <span>
                  Agent <span className="tabular">{snap.agent_id}</span>
                </span>
              )}
            </span>
            {snap.error && (
              <span className="mt-1 inline-flex items-center gap-1 text-[length:var(--fs-11)] text-stale">
                <AlertCircle size={11} aria-hidden />
                {snap.error}
              </span>
            )}
          </div>
        </td>
        <td className={clsx(
          "dt-td text-right tabular align-top",
          snap.current_balance < 0 ? "text-loss" : "text-text-1",
        )}>
          {fmtUsd(snap.current_balance)}
        </td>
        <td className={clsx(
          "dt-td text-right tabular align-top",
          snap.available_balance < 0 ? "text-loss" : "text-text-1",
        )}>
          {fmtUsd(snap.available_balance)}
        </td>
        <td className="dt-td text-right tabular text-text-2 align-top">
          {fmtUsd(snap.pending_wager_balance)}
        </td>
        <td className={clsx(
          "dt-td text-right tabular align-top",
          snap.free_play_balance > 0 ? "text-text-1" : "text-text-3",
        )}>
          {fmtUsd(snap.free_play_balance)}
        </td>
        <td className="dt-td text-right align-top">
          <span className={clsx(
            "tabular font-medium",
            w.open_count === 0 ? "text-text-3" : "text-text-1",
          )}>
            {w.open_count}
          </span>
          {w.open_count > 0 && (
            <span className="block text-[length:var(--fs-11)] text-text-3">
              <span className="tabular">{fmtUsd(w.open_amount_risked)}</span> at risk
            </span>
          )}
        </td>
        <td className="dt-td align-top">
          {w.open_count === 0 ? (
            <span className="text-text-3">—</span>
          ) : (
            <div className="flex flex-col gap-1">
              {/* Type — mutually exclusive, sums to open_count. */}
              <div className="flex flex-wrap gap-1.5">
                {w.straight_count > 0 && (
                  <BetMixChip label="Straight" count={w.straight_count} />
                )}
                {w.parlay_count > 0 && (
                  <BetMixChip
                    label="Parlay"
                    count={w.parlay_count}
                    title="Parlays that are not free plays"
                  />
                )}
                {w.free_play_count > 0 && (
                  <BetMixChip label="Free play" count={w.free_play_count} />
                )}
              </div>
              {/* Progress — the same open bets bucketed by leg state. */}
              <div className="flex flex-wrap gap-1.5">
                {w.won_open_slot_count > 0 && (
                  <BetMixChip
                    label="Won, slot open"
                    count={w.won_open_slot_count}
                    tone="edge"
                    title="A leg has won and the second leg has not been taken yet: a slot to fill"
                  />
                )}
                {w.pending_open_slot_count > 0 && (
                  <BetMixChip
                    label="Pending"
                    count={w.pending_open_slot_count}
                    title="Leg still pending and the second leg has not been taken yet"
                  />
                )}
                {w.fulfilled_count > 0 && (
                  <BetMixChip
                    label="Fulfilled"
                    count={w.fulfilled_count}
                    tone="gain"
                    title="A leg won and the second leg has been taken"
                  />
                )}
              </div>
            </div>
          )}
        </td>
      </tr>
      {isExpanded && (
        <tr className="border-b border-border-subtle bg-bg-1">
          <td colSpan={8} className="px-4 py-4">
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
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
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
        <div className="text-[length:var(--fs-12)] text-text-3">No open wagers</div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-[length:var(--fs-12)] font-medium text-text-2">
            Open wagers{" "}
            <span className="tabular text-text-3">{snap.pending_wagers.length}</span>
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
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
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[length:var(--fs-12)]">
        <span className="text-text-3">{label}</span>
        <span className="text-text-2">
          <span className="tabular">{fmtUsd(used)}</span>
          <span className="text-text-3"> of </span>
          <span className="tabular">{fmtUsd(limit)}</span>
          <span
            className={clsx(
              "tabular ml-2",
              tone === "neutral" ? "text-text-3" : "text-stale",
            )}
          >
            {pct.toFixed(0)}%
          </span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-bg-2 overflow-hidden">
        <div
          className={clsx(
            "h-full rounded-full transition-all",
            tone === "warning" && "bg-stale",
            tone === "caution" && "bg-[rgb(var(--stale-rgb)/0.55)]",
            tone === "neutral" && "bg-[rgb(var(--text-rgb)/0.45)]",
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
    <div className="rounded-md border border-border-subtle bg-bg-0 px-3 py-2.5 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="text-[length:var(--fs-13)] font-medium text-text-1 first-letter:uppercase">
            {title}
          </span>
          {wager.is_partial && <Chip>Partial</Chip>}
          {wager.is_free_play && <Chip>Free play</Chip>}
          <span className="tabular text-[length:var(--fs-11)] text-text-3">
            #{wager.ticket_number}
          </span>
        </div>
        <div className="flex items-baseline gap-3 text-[length:var(--fs-12)] text-text-3">
          <span>
            Risk <span className="tabular text-text-1">{fmtUsd(wager.amount_wagered)}</span>
          </span>
          <span>
            To win <span className="tabular text-text-1">{fmtUsd(wager.to_win_amount)}</span>
          </span>
          <span className="tabular hidden sm:inline">
            {fmtAcceptedAt(wager.accepted_at)}
          </span>
        </div>
      </div>
      <div className="flex flex-col">
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
      // Which side was taken matters more than the number. Coral33 only puts
      // it in the description text, so it can be absent — fall back to the
      // neutral "o/u" rather than guessing a side.
      const side =
        leg.total_side === "over" ? "Over" : leg.total_side === "under" ? "Under" : "o/u";
      return `${side} ${leg.total_points}`;
    }
    return null;
  })();

  const matchup =
    leg.team1 && leg.team2 ? `${leg.team1} @ ${leg.team2}` : null;

  return (
    <div className="flex flex-col gap-0.5 py-1.5 border-t border-border-subtle first:border-t-0 first:pt-0 last:pb-0 min-w-0">
      <div className="flex items-center gap-2 flex-wrap text-[length:var(--fs-12)]">
        <LegStatusDot outcome={leg.outcome} />
        <span className="font-medium text-text-1">
          {leg.chosen_team || leg.description.split(" ")[0]}
        </span>
        {lineLabel && <span className="tabular text-text-2">{lineLabel}</span>}
        <span className="tabular text-text-3">{fmtAmericanOdds(leg.final_money)}</span>
        {leg.period && leg.period !== "Game" && (
          <span className="text-text-3">{leg.period}</span>
        )}
      </div>
      {matchup && (
        <span className="flex gap-2 pl-3.5 text-[length:var(--fs-11)] text-text-3 truncate">
          <span className="truncate">{matchup}</span>
          {leg.sport_sub_type && <span>{leg.sport_sub_type}</span>}
        </span>
      )}
    </div>
  );
}


function LegStatusDot({ outcome }: { outcome: string | null }) {
  const tone =
    outcome === "won"
      ? "bg-gain"
      : outcome === "lost"
        ? "bg-loss"
        : outcome === "push"
          ? "bg-text-3"
          : outcome === "pending"
            ? "bg-text-2"
            : "border border-text-3 bg-transparent";
  const title =
    outcome === "won"
      ? "Won"
      : outcome === "lost"
        ? "Lost"
        : outcome === "push"
          ? "Push"
          : outcome === "pending"
            ? "Pending"
            : "Open";
  return (
    <span
      title={title}
      aria-label={title}
      className={clsx("inline-block w-1.5 h-1.5 shrink-0 rounded-full", tone)}
    />
  );
}


function BetMixChip({
  label,
  count,
  tone = "neutral",
  title,
}: {
  label: string;
  count: number;
  tone?: ChipTone;
  title?: string;
}) {
  return (
    <Chip tone={tone} title={title}>
      {label}
      <span className="tabular">{count}</span>
    </Chip>
  );
}


// ─── Daily balance chart ─────────────────────────────────────────────────

/** Cleared balance and pending wagers are neutral ink — they're amounts,
 * not wins or losses. Only the P&L delta carries gain/loss. */
const CLEARED_FILL = "rgb(var(--text-rgb) / 0.55)";
const PENDING_FILL = "rgb(var(--text-rgb) / 0.22)";

/** Per-account lines: no hue carries account identity (every hue has a job),
 * so accounts are told apart by ink weight plus dash pattern. */
const SPLIT_STYLES: { color: string; dash?: string }[] = [
  { color: "rgb(var(--text-rgb) / 0.92)" },
  { color: "rgb(var(--text-rgb) / 0.70)" },
  { color: "rgb(var(--text-rgb) / 0.50)" },
  { color: "rgb(var(--text-rgb) / 0.34)" },
  { color: "rgb(var(--text-rgb) / 0.92)", dash: "5 3" },
  { color: "rgb(var(--text-rgb) / 0.70)", dash: "5 3" },
  { color: "rgb(var(--text-rgb) / 0.50)", dash: "2 3" },
  { color: "rgb(var(--text-rgb) / 0.34)", dash: "2 3" },
];

type ChartMode = "total" | "split";

interface ChartSeries {
  customer_id: string;
  label: string;
  color: string;
  dash?: string;
  points: HistoryPoint[];
}

function SeriesSwatch({ color, dash }: { color: string; dash?: string }) {
  return (
    <svg width="14" height="6" aria-hidden className="shrink-0">
      <line x1="0" x2="14" y1="3" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dash} />
    </svg>
  );
}

function PnLChart({ history }: { history: HistoryRollup }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [mode, setMode] = useState<ChartMode>("total");

  const accountSeries = useMemo<ChartSeries[]>(() => {
    return history.accounts
      .filter(a => a.points.length > 0)
      .map((a, i) => {
        const style = SPLIT_STYLES[i % SPLIT_STYLES.length];
        return {
          customer_id: a.customer_id,
          label: a.label,
          color: style.color,
          dash: style.dash,
          points: a.points,
        };
      });
  }, [history]);

  // Combined-total series: at each timestep, sum balance and net across
  // every account. Built once regardless of mode so the toggle is a no-op
  // re-render rather than a recompute.
  const totalSeries = useMemo<ChartSeries | null>(() => {
    if (accountSeries.length === 0) return null;
    return { ...buildTotalHistory(accountSeries), color: CLEARED_FILL };
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
  const latestPending =
    totalSeries.points[totalSeries.points.length - 1]?.pending ?? 0;

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

  const axisText = { fontSize: "var(--fs-11)" } as const;

  return (
    <Panel
      title={
        <>
          Daily balance{" "}
          <span className="font-normal text-text-3">
            last <span className="tabular">{history.weeks}</span> weeks
          </span>
        </>
      }
      actions={
        <Segmented<ChartMode>
          size="sm"
          ariaLabel="Chart aggregation"
          value={mode}
          onChange={setMode}
          options={[
            { value: "total", label: "Total" },
            { value: "split", label: "Per account" },
          ]}
        />
      }
      bodyClassName="px-4 pt-3 pb-3 flex flex-col gap-2"
    >
      <div className="flex items-baseline justify-between gap-x-6 gap-y-2 flex-wrap">
        <div className="flex items-baseline gap-3">
          <span className="tabular text-[length:var(--fs-22)] leading-[var(--lh-22)] font-semibold text-text-1">
            {fmtUsd(endBalance)}
          </span>
          <span
            className={clsx(
              "tabular text-[length:var(--fs-13)]",
              totalChange > 0 && "text-gain",
              totalChange < 0 && "text-loss",
              totalChange === 0 && "text-text-3",
            )}
          >
            {fmtSignedUsd(totalChange)}
          </span>
          <span className="text-[length:var(--fs-12)] text-text-3">over the period</span>
        </div>

        {mode === "total" ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--fs-12)] text-text-2">
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-2 w-2 rounded-[2px]" style={{ background: CLEARED_FILL }} />
              Cleared
              <span className="tabular text-text-3">{fmtUsd(endBalance)}</span>
            </span>
            {latestPending > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2 w-2 rounded-[2px]" style={{ background: PENDING_FILL }} />
                Pending
                <span className="tabular text-text-3">{fmtUsd(latestPending)}</span>
              </span>
            )}
          </div>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--fs-12)] text-text-2">
            {accountSeries.map(s => (
              <span key={s.customer_id} className="inline-flex items-center gap-1.5">
                <SeriesSwatch color={s.color} dash={s.dash} />
                {s.label}
                <span className="tabular text-text-3">
                  {fmtUsd(s.points[s.points.length - 1]?.balance ?? 0)}
                </span>
              </span>
            ))}
          </div>
        )}
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
              strokeDasharray="2 3"
              strokeWidth={0.5}
            />
            <text
              x={padL - 6}
              y={yAt(tv) + 3}
              textAnchor="end"
              className="tabular text-text-3"
              style={axisText}
              fill="currentColor"
            >
              {fmtUsd(tv, { compact: true })}
            </text>
          </g>
        ))}

        {/* Zero baseline */}
        <line
          x1={padL}
          x2={W - padR}
          y1={yAt(0)}
          y2={yAt(0)}
          stroke="var(--color-text-3)"
          strokeWidth={0.75}
        />

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
              className="tabular text-text-3"
              style={axisText}
              fill="currentColor"
            >
              {p.date.slice(5)}
            </text>
          );
        })}

        {/* Bars (total mode) or lines (split mode).
            Total mode renders ONE stacked bar per day: a cleared balance
            segment + a lighter pending cap on top. Pending only has data
            on the latest point today — older bars omit the cap.
            Split mode keeps the thin-line per-account view since stacking
            8 accounts × 84 days into bars produces sub-pixel widths and a
            busy frame. */}
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
              const dim = hoverIdx != null && hoverIdx !== i;
              return (
                <g key={i} opacity={dim ? 0.55 : 1}>
                  <rect
                    x={x}
                    y={balTop}
                    width={barW}
                    height={balH}
                    rx={1}
                    fill={CLEARED_FILL}
                  />
                  {p.pending > 0 && pendingH > 0 && (
                    <rect
                      x={x}
                      y={yBalPlusPending}
                      width={barW}
                      height={pendingH}
                      rx={1}
                      fill={PENDING_FILL}
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
                strokeDasharray={s.dash}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })
        )}

        {/* Hover marker. Total mode: a faint highlight spanning the
            hovered bar's slot. Split mode: dashed vertical line + a dot on
            each line. */}
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
                  stroke="var(--color-bg-1)"
                  strokeWidth={1.5}
                />
              );
            })}
          </>
        )}
      </svg>

      {/* Fixed-height readout so hovering never shifts the layout. */}
      <div className="min-h-[18px] flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--fs-12)] text-text-2">
        {hoverIdx != null ? (
          <>
            <span className="tabular text-text-3">
              {series[0].points[hoverIdx]?.date}
            </span>
            {series.map(s => {
              const p = s.points[hoverIdx];
              if (!p) return null;
              return (
                <span key={s.customer_id} className="inline-flex items-center gap-1.5">
                  {mode === "split" && <SeriesSwatch color={s.color} dash={s.dash} />}
                  <span className="text-text-3">{s.label}</span>
                  <span
                    className={clsx(
                      "tabular",
                      p.net > 0 && "text-gain",
                      p.net < 0 && "text-loss",
                      p.net === 0 && "text-text-2",
                    )}
                  >
                    {fmtSignedUsd(p.net)}
                  </span>
                  <span className="text-text-3">
                    balance <span className="tabular text-text-2">{fmtUsd(p.balance)}</span>
                  </span>
                  {p.pending > 0 && (
                    <span className="text-text-3">
                      pending <span className="tabular text-text-2">{fmtUsd(p.pending)}</span>
                    </span>
                  )}
                </span>
              );
            })}
          </>
        ) : (
          <span className="text-text-3">Hover the chart for a day&apos;s P&amp;L</span>
        )}
      </div>
    </Panel>
  );
}
