"use client";
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";

import { BookLogo } from "@/components/book-logo";
import { formatAmerican, timeAgo } from "@/lib/format";
import {
  MODE_LONG_LABEL,
  type EdgeOpportunity,
  marketLabel,
} from "@/lib/edges";
import {
  computeWorkbenchMath,
  type RoundIncrement,
} from "@/lib/stake-calc";
import { getBookDeeplink } from "@/lib/book-deeplinks";
import { bookInfo } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";

const BANKROLL_KEY = "bankroll";
const KELLY_FRAC_KEY = "edges-kelly-frac";
const ROUND_KEY = "edges-round";

const ROUND_OPTIONS: RoundIncrement[] = [1, 5, 25, 100];

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

/**
 * Inline workbench panel — three columns side-by-side on ≥1024 viewports,
 * stacks vertically below. Opens underneath its parent row and its left
 * edge carries a 2px accent strip that visually ties it to the expand
 * caret cell above.
 *
 * Props:
 *   op    — the row being expanded.
 *   stake — user's current stake input (persisted on the page).
 *
 * State not passed in (bankroll, Kelly fraction, round increment) is
 * managed locally with localStorage — these are true personal defaults
 * that should survive reloads and aren't part of a bookmarkable URL.
 */
export function Workbench({
  op,
  stake,
}: {
  op: EdgeOpportunity;
  stake: number;
}) {
  const [bankroll, setBankroll] = useState<number>(1000);
  const [kellyFrac, setKellyFrac] = useState<number>(0.25);
  const [rounding, setRounding] = useState<RoundIncrement>(5);

  useEffect(() => {
    try {
      const br = window.localStorage.getItem(BANKROLL_KEY);
      if (br) {
        const n = Number(br);
        if (Number.isFinite(n) && n > 0) setBankroll(clamp(n, 10, 10_000_000));
      }
      const kf = window.localStorage.getItem(KELLY_FRAC_KEY);
      if (kf) {
        const n = Number(kf);
        if (Number.isFinite(n) && n > 0 && n <= 1) setKellyFrac(n);
      }
      const r = window.localStorage.getItem(ROUND_KEY);
      if (r) {
        const n = Number(r);
        if (n === 1 || n === 5 || n === 25 || n === 100) setRounding(n);
      }
    } catch {}
  }, []);

  const persistBankroll = useCallback((v: number) => {
    setBankroll(v);
    try {
      window.localStorage.setItem(BANKROLL_KEY, String(v));
    } catch {}
  }, []);
  const persistKelly = useCallback((v: number) => {
    setKellyFrac(v);
    try {
      window.localStorage.setItem(KELLY_FRAC_KEY, String(v));
    } catch {}
  }, []);
  const persistRound = useCallback((v: RoundIncrement) => {
    setRounding(v);
    try {
      window.localStorage.setItem(ROUND_KEY, String(v));
    } catch {}
  }, []);

  const math = computeWorkbenchMath(op, {
    bankroll,
    kelly_fraction: kellyFrac,
    rounding,
    stake,
  });

  const handleCopy = useCallback(() => {
    const parts: string[] = [];
    parts.push(sportLabel(op.sport_key));
    parts.push(`${op.away_team} vs ${op.home_team}`);
    parts.push(`${marketLabel(op)} ${op.raw && "outcome_name" in op.raw ? op.raw.outcome_name : ""}`.trim());
    const offered = op.legs.find(l => l.role === "offered" || l.role === "a");
    if (offered) {
      const info = bookInfo(offered.book);
      parts.push(`@ ${formatAmerican(offered.price_american)} ${info.name}`);
    }
    if (op.mode === "ev") {
      parts.push(
        `EV ${op.edge_pct >= 0 ? "+" : ""}${op.edge_pct.toFixed(2)}%`,
      );
      parts.push(`Fair ${formatAmerican(op.raw.fair_price_american)}`);
    } else if (op.mode === "arb") {
      parts.push(`ROI +${op.raw.roi_pct.toFixed(2)}%`);
    } else if (op.mode === "low_hold") {
      parts.push(`Hold ${op.raw.hold_pct.toFixed(2)}%`);
    } else {
      parts.push(`Conv ${op.raw.conversion_pct.toFixed(1)}%`);
    }
    const text = parts.join(" · ");
    try {
      void navigator.clipboard.writeText(text);
    } catch {}
  }, [op]);

  const handleLedger = useCallback(() => {
    // Stub — the ledger schema + endpoint live behind a future task.
    // Keeping this toast shallow so wiring it up is a one-file change.
    console.warn("[ledger] Save-to-ledger is not implemented yet.", op.row_key);
    alert("Save to ledger — not implemented yet.");
  }, [op]);

  return (
    <div
      className={clsx(
        "bg-bg-2 border-l-2 border-accent",
        "grid gap-4 px-4 py-4",
        // 3-column at ≥1024, single-column below
        "grid-cols-1 lg:grid-cols-3",
      )}
    >
      {/* Panel A — Stake calculator ─────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <header className="flex items-baseline justify-between">
          <h4 className="text-[10px] uppercase tracking-wider text-text-3 font-semibold">
            Stake calculator
          </h4>
          <span className="text-[10px] uppercase tracking-wider text-text-3">
            {MODE_LONG_LABEL[op.mode]}
          </span>
        </header>

        <div className="flex items-center gap-2">
          <label className="text-[10px] uppercase tracking-wider text-text-3 w-20">
            Bankroll
          </label>
          <div className="flex-1 inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle px-2 py-1">
            <span className="text-text-3 text-xs">$</span>
            <input
              type="number"
              value={bankroll}
              onChange={e =>
                persistBankroll(clamp(Number(e.target.value) || 0, 10, 10_000_000))
              }
              min={10}
              step={50}
              className="w-full bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
          </div>
        </div>

        {op.mode === "ev" && (
          <div className="flex items-center gap-2">
            <label className="text-[10px] uppercase tracking-wider text-text-3 w-20">
              Kelly frac
            </label>
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={kellyFrac}
              onChange={e => persistKelly(Number(e.target.value))}
              className="flex-1 accent-accent"
            />
            <span className="tabular text-xs text-text-1 w-12 text-right">
              {kellyFrac.toFixed(2)}×
            </span>
          </div>
        )}

        <div className="flex items-center gap-2">
          <label className="text-[10px] uppercase tracking-wider text-text-3 w-20">
            Round to
          </label>
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {ROUND_OPTIONS.map(r => (
              <button
                key={r}
                onClick={() => persistRound(r)}
                className={clsx(
                  "px-2.5 py-1 text-[11px] tabular transition-colors rounded-sm",
                  rounding === r
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1",
                )}
              >
                ${r}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-1 flex flex-col gap-1 border-t border-border-subtle pt-2">
          <div className="flex items-baseline justify-between">
            <span className="text-[10px] uppercase tracking-wider text-text-3">
              Stake
            </span>
            <span className="tabular text-sm text-text-1 font-semibold">
              {math.primary_stake_label}
            </span>
          </div>
          <div className="flex items-baseline justify-between">
            <span className="text-[10px] uppercase tracking-wider text-text-3">
              Profit
            </span>
            <span className="tabular text-xs text-price-up">
              {math.profit_label}
            </span>
          </div>
          <ul className="mt-1 flex flex-col gap-0.5">
            {op.legs.map((leg, i) => (
              <li
                key={i}
                className="flex items-center justify-between text-[11px] text-text-2"
              >
                <span className="inline-flex items-center gap-1.5">
                  <BookLogo bookKey={leg.book} mode="label" />
                  <span className="tabular">
                    {formatAmerican(leg.price_american)}
                  </span>
                  <span className="text-text-3 uppercase tracking-wider text-[9px]">
                    {leg.role}
                  </span>
                </span>
                <span className="tabular text-text-1">
                  {math.legs[i]?.stake_label ?? ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Panel B — Deeplinks + copy ─────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <header>
          <h4 className="text-[10px] uppercase tracking-wider text-text-3 font-semibold">
            Book actions
          </h4>
        </header>
        <div className="flex flex-col gap-1.5">
          {op.legs
            .filter(l => l.role !== "fair")
            .map((leg, i) => {
              const url = getBookDeeplink(op, leg);
              const info = bookInfo(leg.book);
              const disabled = url == null;
              return (
                <a
                  key={i}
                  href={url ?? undefined}
                  target={url ? "_blank" : undefined}
                  rel={url ? "noopener noreferrer" : undefined}
                  aria-disabled={disabled}
                  title={
                    disabled
                      ? "Deeplink not configured — open book manually."
                      : `Open bet slip at ${info.name}`
                  }
                  onClick={e => {
                    if (disabled) e.preventDefault();
                  }}
                  className={clsx(
                    "inline-flex items-center justify-between gap-2 h-9 px-3 rounded-md border text-xs font-medium transition-colors",
                    disabled
                      ? "border-border-subtle bg-bg-1 text-text-3 cursor-not-allowed"
                      : "border-accent/50 bg-accent/10 text-accent hover:bg-accent/15",
                  )}
                >
                  <span className="inline-flex items-center gap-2">
                    <BookLogo bookKey={leg.book} mode="label" />
                    <span>Open in {info.name}</span>
                  </span>
                  <span className="tabular text-[11px]">
                    {formatAmerican(leg.price_american)}
                  </span>
                </a>
              );
            })}
        </div>
        <div className="flex flex-col gap-1.5 mt-auto">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center justify-center h-8 px-3 rounded-md border border-border-subtle bg-bg-1 text-xs text-text-2 hover:text-text-1 transition-colors"
            title="Copy a compact text summary of this bet to your clipboard."
          >
            Copy to clipboard
          </button>
          <button
            type="button"
            onClick={handleLedger}
            className="inline-flex items-center justify-center h-8 px-3 rounded-md border border-border-subtle bg-bg-1 text-xs text-text-3 hover:text-text-2 transition-colors"
            title="Save this bet to the ledger (not implemented yet)."
          >
            Save to ledger
          </button>
        </div>
      </section>

      {/* Panel C — Flags / context ──────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <header>
          <h4 className="text-[10px] uppercase tracking-wider text-text-3 font-semibold">
            Flags & context
          </h4>
        </header>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-3 uppercase tracking-wider text-[10px]">
              Commence
            </span>
            <span
              className="text-text-2 tabular"
              title={new Date(op.commence_time).toString()}
            >
              {timeAgo(op.commence_time).replace(" ago", "")} · {new Date(op.commence_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>

          {op.mode === "ev" && (
            <>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-3 uppercase tracking-wider text-[10px]">
                  Offered age
                </span>
                <span
                  className={clsx(
                    "tabular",
                    op.stale ? "text-flash" : "text-text-2",
                  )}
                >
                  {op.row_age_s}s
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-3 uppercase tracking-wider text-[10px]">
                  Anchor
                </span>
                <span
                  className={clsx(
                    "inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider",
                    op.anchor === "pinnacle"
                      ? "text-accent bg-accent/10"
                      : "text-text-3 bg-bg-1",
                  )}
                >
                  {op.anchor === "pinnacle"
                    ? "PIN"
                    : `CON · ${op.raw.anchor_book_count} books`}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-3 uppercase tracking-wider text-[10px]">
                  Fair price
                </span>
                <span className="tabular text-text-1">
                  {formatAmerican(op.raw.fair_price_american)}
                </span>
              </div>
            </>
          )}

          <div className="flex flex-wrap gap-1 pt-1">
            {op.also_in_arb && op.mode !== "arb" && (
              <span
                className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-up bg-price-up/20"
                title="Also appears as an arbitrage pair."
              >
                ALSO IN ARB
              </span>
            )}
            {op.suspicious && (
              <span
                className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-down bg-price-down/10"
                title="Very high EV — likely mispriced or stale. Verify before betting."
              >
                SUS
              </span>
            )}
            {op.stale && (
              <span
                className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-text-3 bg-bg-1"
                title={`Row age ${op.row_age_s}s — refresh before firing.`}
              >
                STALE
              </span>
            )}
            {op.legs
              .filter(l => l.role !== "fair")
              .map((leg, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 px-1 rounded-sm text-[9px] tracking-wider text-text-3 bg-bg-1"
                  title={`Leg ${i + 1} price @ ${bookInfo(leg.book).name}`}
                >
                  <BookLogo bookKey={leg.book} mode="label" />
                  {formatAmerican(leg.price_american)}
                </span>
              ))}
          </div>
        </div>
      </section>
    </div>
  );
}
