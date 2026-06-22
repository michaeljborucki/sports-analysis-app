"use client";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import useSWR from "swr";
import clsx from "clsx";
import { X } from "lucide-react";

import { BookLogo } from "@/components/book-logo";
import { formatAmerican } from "@/lib/format";
import {
  type AccountSnapshot,
  type SplitPlan,
  planSplits,
} from "@/lib/sidecar/splitter";
import {
  useSidecarStream,
  type SidecarEvent,
} from "@/lib/sidecar/useSidecarStream";
import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Two-team-parlay open-spot multiplier on a -110 fill. The HAR-captured
 * `getInfoParlay` request returns 1.909... per leg for a -110 spot; rounded
 * to three places for the modal's expected-win preview. Real placements
 * read the live value from the placement chain; this is a UX preview.
 */
const OPEN_SPOT_DECIMAL_AT_MINUS_110 = 1.909;

/**
 * Kelly fractions for the radio group. The default ("half") is the user's
 * sidecar_default_kelly setting, but this preview lets them dial it before
 * confirming a single placement.
 */
export type KellyFraction = "full" | "half" | "quarter";

const KELLY_OPTIONS: { value: KellyFraction; label: string; mult: number }[] = [
  { value: "full", label: "Full", mult: 1 },
  { value: "half", label: "Half", mult: 0.5 },
  { value: "quarter", label: "Quarter", mult: 0.25 },
];

interface SidecarModeResponse {
  mode: "off" | "dry-run" | "live";
}

interface AccountsResponse {
  snapshots: Array<{
    customer_id: string;
    label: string;
    available_balance: number;
    /** Server returns max_parlay_stake once Phase A/H wire it through;
        until then this is undefined and we fall back to 100. */
    max_parlay_stake?: number;
  }>;
}

interface UserSettingsResponse {
  sidecar_bankroll?: number;
  sidecar_default_kelly?: KellyFraction;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

export interface ConfirmModalProps {
  evRowId: string;
  /** Used in the header chip. */
  sportKey: string;
  /** Used in the header label, e.g. "Spread", "Moneyline". */
  marketLabel: string;
  /** Used in the header label, e.g. "Patriots +3.5". */
  sideLabel: string;
  /** Offered price at the +EV book (Coral33), e.g. +475. */
  offeredPriceAmerican: number;
  /** EV % shown in the modal header chip. */
  evPct: number;
  /** Server-computed full-Kelly fraction (0-1). Multiplied by the
      selected radio fraction below to compute target stake. */
  fullKellyPct: number;
  onClose: () => void;
}

/**
 * Auto-place confirm modal. Renders a center-screen card with:
 *   - Header  : EV% chip + Kelly% chip + market/side/price
 *   - Radio   : Full / Half / Quarter Kelly fraction
 *   - Strip   : Target stake → expected win at 2-team open-spot decimal odds
 *   - Plan    : Live preview of the splitter's account assignments
 *   - Footer  : Mode badge + Cancel + Confirm
 *   - Receipt : Per-leg events stream after Confirm
 *
 * Layout intentionally matches the Bloomberg-terminal palette (dark mode,
 * tabular figures) — every chip and stake reads in `text-text-1` /
 * `text-text-2` / `bg-bg-2` so the modal looks at home inside /edges.
 *
 * Phase F (server) hasn't wired POST /api/sidecar/place yet; the confirm
 * handler attempts the POST anyway so this modal works end-to-end the
 * moment the endpoint lands. Until then, Confirm will show a transient
 * error and the receipt section stays empty.
 */
export function ConfirmModal({
  evRowId,
  sportKey,
  marketLabel,
  sideLabel,
  offeredPriceAmerican,
  evPct,
  fullKellyPct,
  onClose,
}: ConfirmModalProps) {
  const mounted = useIsMounted();

  const { data: settings } = useSWR<UserSettingsResponse>(
    "/api/settings",
    fetchJson,
  );
  const { data: accountsData } = useSWR<AccountsResponse>(
    "/api/coral33/accounts",
    fetchJson,
  );
  const { data: modeData } = useSWR<SidecarModeResponse>(
    "/api/sidecar/mode",
    fetchJson,
    { refreshInterval: 5_000 },
  );

  // Kelly fraction is derived from user settings until the user clicks a
  // radio in this modal. Once they pick (userFraction !== null), their
  // explicit choice wins. Using null-as-untouched avoids syncing settings
  // into state via useEffect, which triggers React 19's
  // "setState in effect → cascading renders" lint warning.
  const [userFraction, setUserFraction] = useState<KellyFraction | null>(null);
  const fraction: KellyFraction =
    userFraction ?? settings?.sidecar_default_kelly ?? "half";
  const setFraction = (next: KellyFraction) => setUserFraction(next);

  const bankroll = settings?.sidecar_bankroll ?? 10_000;
  const mult = KELLY_OPTIONS.find((o) => o.value === fraction)?.mult ?? 0.5;
  const kellyPct = fullKellyPct * mult;
  const target = Math.max(0, Math.round(kellyPct * bankroll));

  const decimalOdds =
    offeredPriceAmerican > 0
      ? offeredPriceAmerican / 100 + 1
      : -100 / offeredPriceAmerican + 1;

  // 2-team open-spot parlay payout: target × leg_decimal × 1.909 minus stake.
  const grossPayout = target * decimalOdds * OPEN_SPOT_DECIMAL_AT_MINUS_110;
  const profit = grossPayout - target;

  const accountSnapshots = useMemo<AccountSnapshot[]>(() => {
    if (!accountsData?.snapshots) return [];
    return accountsData.snapshots.map((s) => ({
      customer_id: s.customer_id,
      label: s.label,
      available_balance: s.available_balance,
      max_parlay_stake: s.max_parlay_stake ?? 100,
    }));
  }, [accountsData]);

  const plan: SplitPlan | null = useMemo(() => {
    if (accountSnapshots.length === 0) return null;
    return planSplits(target, accountSnapshots);
  }, [target, accountSnapshots]);

  // --- Confirm + receipt-sequence stream wiring ---
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const events = useSidecarStream(jobId);

  async function handleConfirm() {
    if (!plan || plan.status === "below_minimum" || plan.status === "no_eligible_account") {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await fetch(`${API_BASE}/api/sidecar/place`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ev_row_id: evRowId,
          kelly_fraction: fraction,
        }),
      });
      if (!res.ok) {
        throw new Error(`POST /api/sidecar/place → ${res.status}`);
      }
      const body = (await res.json()) as { job_id: string };
      setJobId(body.job_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  // Escape-to-close. Suppress while a placement is mid-flight so the
  // user can't accidentally bail out before receipts arrive.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [submitting, onClose]);

  if (!mounted) return null;

  const mode = modeData?.mode ?? "off";
  const canConfirm =
    plan != null &&
    plan.status !== "below_minimum" &&
    plan.status !== "no_eligible_account" &&
    mode !== "off" &&
    jobId === null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Confirm auto-place"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        className={clsx(
          "w-[min(560px,92vw)] max-h-[80vh] overflow-y-auto",
          "rounded-md border border-border-subtle bg-bg-1 shadow-2xl",
        )}
      >
        {/* Header */}
        <header className="sticky top-0 z-10 bg-bg-1 border-b border-border-subtle px-4 py-3 flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider text-violet-accent bg-violet-accent/15">
                EV {evPct >= 0 ? "+" : ""}
                {evPct.toFixed(2)}%
              </span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider text-accent bg-accent/15">
                KELLY {(kellyPct * 100).toFixed(2)}%
              </span>
              <span className="text-text-3 text-[10px] uppercase tracking-wide">
                {sportKey}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[12px]">
              <BookLogo bookKey="coral33" mode="label" />
              <span className="text-text-2">{marketLabel}</span>
              <span className="text-text-1 font-medium">{sideLabel}</span>
              <span className="text-price-up font-semibold tabular">
                {formatAmerican(offeredPriceAmerican)}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
            className={clsx(
              "shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-sm",
              "text-text-3 hover:text-text-1 hover:bg-bg-2 transition-colors",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            )}
            title="Close (Esc)"
          >
            <X size={14} aria-hidden />
          </button>
        </header>

        {/* Kelly radio */}
        <section className="px-4 py-3 border-b border-border-subtle">
          <div className="text-text-3 text-[10px] uppercase tracking-wide mb-1.5">
            Kelly fraction
          </div>
          <div className="inline-flex rounded-sm border border-border-subtle overflow-hidden bg-bg-0">
            {KELLY_OPTIONS.map((opt) => {
              const active = fraction === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setFraction(opt.value)}
                  disabled={jobId !== null}
                  className={clsx(
                    "px-3 py-1.5 text-[11px] font-semibold tracking-wider uppercase",
                    "border-r border-border-subtle last:border-r-0",
                    "transition-colors",
                    active
                      ? "bg-accent text-bg-0"
                      : "text-text-2 hover:text-text-1 hover:bg-bg-1",
                    "disabled:opacity-40 disabled:cursor-not-allowed",
                  )}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </section>

        {/* Expected payout strip */}
        <section className="px-4 py-3 border-b border-border-subtle grid grid-cols-3 gap-3">
          <div>
            <div className="text-text-3 text-[10px] uppercase tracking-wide">
              Target stake
            </div>
            <div className="text-text-1 tabular text-[16px] font-semibold mt-0.5">
              ${target.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-text-3 text-[10px] uppercase tracking-wide">
              Leg × open-spot
            </div>
            <div className="text-text-2 tabular text-[12px] mt-0.5">
              {decimalOdds.toFixed(3)} ×{" "}
              {OPEN_SPOT_DECIMAL_AT_MINUS_110.toFixed(3)}
            </div>
          </div>
          <div>
            <div className="text-text-3 text-[10px] uppercase tracking-wide">
              Expected profit
            </div>
            <div className="text-price-up tabular text-[16px] font-semibold mt-0.5">
              ${profit.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
          </div>
        </section>

        {/* Split plan preview */}
        <section className="px-4 py-3 border-b border-border-subtle">
          <div className="text-text-3 text-[10px] uppercase tracking-wide mb-1.5">
            Split plan
          </div>
          <SplitPlanPreview plan={plan} />
        </section>

        {/* Receipt sequence (after confirm) */}
        {jobId !== null && (
          <section className="px-4 py-3 border-b border-border-subtle">
            <div className="text-text-3 text-[10px] uppercase tracking-wide mb-1.5">
              Placements ({events.length}
              {plan ? ` / ${plan.assignments.length}` : ""})
            </div>
            <ReceiptSequence events={events} />
          </section>
        )}

        {/* Footer */}
        <footer className="px-4 py-3 flex items-center justify-between gap-3 bg-bg-1">
          <ModeBadge mode={mode} />
          {submitError && (
            <span
              className="text-price-down text-[11px] tabular truncate"
              title={submitError}
            >
              {submitError}
            </span>
          )}
          <div className="flex items-center gap-2 ml-auto">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className={clsx(
                "px-3 py-1.5 text-[11px] font-semibold tracking-wider uppercase rounded-sm",
                "text-text-2 hover:text-text-1 hover:bg-bg-2 transition-colors",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              )}
            >
              {jobId !== null ? "Close" : "Cancel"}
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={!canConfirm || submitting}
              className={clsx(
                "px-3 py-1.5 text-[11px] font-semibold tracking-wider uppercase rounded-sm",
                "transition-colors",
                canConfirm && !submitting
                  ? "bg-accent text-bg-0 hover:brightness-110"
                  : "bg-bg-2 text-text-3 cursor-not-allowed",
              )}
              title={
                mode === "off"
                  ? "Sidecar mode is OFF — flip to dry-run or live in /sidecar"
                  : undefined
              }
            >
              {submitting
                ? "Placing…"
                : mode === "dry-run"
                  ? "Confirm (dry-run)"
                  : "Confirm"}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

function SplitPlanPreview({ plan }: { plan: SplitPlan | null }) {
  if (plan === null) {
    return (
      <div className="text-text-3 text-[11px] italic">
        Loading account pool…
      </div>
    );
  }
  if (plan.status === "below_minimum") {
    return (
      <div className="text-text-3 text-[11px]">
        Target ${plan.target} below per-parlay floor ($30).
      </div>
    );
  }
  if (plan.status === "no_eligible_account") {
    return (
      <div className="text-price-down text-[11px]">
        No account in the pool has $30+ available.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {plan.assignments.map((a, i) => (
        <div
          key={`${a.account.customer_id}-${i}`}
          className="flex items-center justify-between text-[11px]"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-text-3 tabular text-[10px] w-5 text-right">
              {i + 1}.
            </span>
            <span className="text-text-1 truncate">
              {a.account.label ?? a.account.customer_id}
            </span>
            <span className="text-text-3 tabular text-[10px]">
              {a.account.customer_id}
            </span>
          </div>
          <span className="text-text-1 tabular font-semibold">
            ${a.amount}
          </span>
        </div>
      ))}
      {plan.status === "partial_fill" && (
        <div className="mt-1 text-flash text-[11px]">
          Partial fill: ${plan.filled} of ${plan.target} (${plan.unfilled}{" "}
          unfilled).
        </div>
      )}
    </div>
  );
}

function ReceiptSequence({ events }: { events: SidecarEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-text-3 text-[11px] italic">
        Waiting for placement events…
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {events.map((e, i) => {
        const ok = e.type === "sidecar_placement" && (e.result === "placed" || e.result === "dry_run");
        return (
          <div
            key={`${e.placement_id}-${i}`}
            className="flex items-center justify-between text-[11px]"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={clsx(
                  "inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider",
                  ok
                    ? "text-price-up bg-price-up/15"
                    : "text-price-down bg-price-down/10",
                )}
              >
                {e.type === "sidecar_placement" ? e.result : "PARTIAL"}
              </span>
              {e.type === "sidecar_placement" && e.picked_account && (
                <span className="text-text-1 truncate">{e.picked_account}</span>
              )}
              {e.type === "sidecar_placement" && e.ticket_number && (
                <span className="text-text-3 tabular text-[10px]">
                  #{e.ticket_number}
                </span>
              )}
            </div>
            {e.type === "sidecar_placement" && e.stake != null && (
              <span className="text-text-1 tabular font-semibold">
                ${e.stake}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ModeBadge({ mode }: { mode: "off" | "dry-run" | "live" }) {
  const meta =
    mode === "live"
      ? { label: "LIVE", className: "text-price-up bg-price-up/15" }
      : mode === "dry-run"
        ? { label: "DRY-RUN", className: "text-flash bg-flash/15" }
        : { label: "OFF", className: "text-text-3 bg-bg-2" };
  return (
    <span
      className={clsx(
        "inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider",
        meta.className,
      )}
      title={`Sidecar mode: ${mode}`}
    >
      {meta.label}
    </span>
  );
}
