"use client";
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { Check, Copy, ExternalLink } from "lucide-react";

import { BookLogo } from "@/components/book-logo";
import { Chip, Segmented, formatAgeShort } from "@/components/ui";
import { formatAmerican } from "@/lib/format";
import {
  type EdgeLeg,
  type EdgeOpportunity,
  formatOutcomeLabel,
  marketLabel,
} from "@/lib/edges";
import {
  americanToDecimal,
  computeWorkbenchMath,
  type RoundIncrement,
} from "@/lib/stake-calc";
import {
  setBankroll as persistBankrollPref,
  setKellyFrac as persistKellyFracPref,
  setRounding as persistRoundingPref,
  useEdgesPrefs,
} from "@/lib/use-edges-prefs";
import { getBookDeeplink } from "@/lib/book-deeplinks";
import { bookInfo } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";

const ROUND_OPTIONS: RoundIncrement[] = [1, 5, 25, 100];

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

/** Parse a typed American price ("-115", "+140", "140"). Null unless |n| >= 100. */
function parseAmerican(s: string): number | null {
  const n = Number(s.trim().replace(/^\+/, ""));
  if (!Number.isFinite(n) || Math.abs(n) < 100) return null;
  return Math.round(n);
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

/**
 * Split a stake-calc label ("+$12.34 guaranteed", "$520 hedge") into the
 * headline amount and the trailing words. Display only — the math and the
 * label strings come from lib/stake-calc.ts unchanged.
 */
function splitLabel(label: string): { amount: string; rest: string } {
  const i = label.indexOf(" ");
  if (i < 0) return { amount: label, rest: "" };
  const rest = label.slice(i + 1).replace(/^\((.*)\)$/, "$1");
  return { amount: label.slice(0, i), rest: rest.charAt(0).toUpperCase() + rest.slice(1) };
}

function legRoleLabel(op: EdgeOpportunity, leg: EdgeLeg, i: number): string {
  if (op.mode === "free_bet") return leg.role === "offered" ? "Free bet" : "Hedge";
  if (op.mode === "profit_boost") return leg.role === "offered" ? "Boosted leg" : "Hedge";
  if (op.mode === "ev") return "Bet";
  return i === 0 ? "Leg one" : "Leg two";
}

const LABEL = "text-[length:var(--fs-12)] text-text-3";

/**
 * Inline workbench under an expanded row: stake tiles per leg, the locked
 * profit / expected value tile, sizing controls, and book actions.
 *
 * Bankroll, Kelly fraction, and rounding live in the shared useEdgesPrefs
 * store so the table's Stake column updates live when edited here.
 */
export function Workbench({
  op,
  stake,
}: {
  op: EdgeOpportunity;
  stake: number;
}) {
  const { bankroll, kellyFrac, rounding } = useEdgesPrefs();
  const [copied, setCopied] = useState(false);
  // EV only: the price you actually see at the book when it has moved since
  // the last fetch. Local to this workbench — collapsing the row clears it.
  const [priceDraft, setPriceDraft] = useState("");
  const overridePrice = op.mode === "ev" ? parseAmerican(priceDraft) : null;
  const effOp: EdgeOpportunity =
    op.mode === "ev" && overridePrice != null
      ? {
          ...op,
          raw: { ...op.raw, offered_price_american: overridePrice },
          legs: op.legs.map(l => (l.role === "offered" ? { ...l, price_american: overridePrice } : l)),
        }
      : op;
  const overrideEvPct =
    op.mode === "ev" && overridePrice != null
      ? (op.raw.fair_probability * americanToDecimal(overridePrice) - 1) * 100
      : null;

  const persistBankroll = useCallback((v: number) => {
    persistBankrollPref(clamp(v, 10, 10_000_000));
  }, []);
  const persistKelly = useCallback((v: number) => {
    persistKellyFracPref(clamp(v, 0.01, 1));
  }, []);
  const persistRound = useCallback((v: RoundIncrement) => {
    persistRoundingPref(v);
  }, []);

  const math = computeWorkbenchMath(effOp, {
    bankroll,
    kelly_fraction: kellyFrac,
    rounding,
    stake,
  });

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);

  const handleCopy = useCallback(() => {
    const parts: string[] = [];
    parts.push(sportLabel(op.sport_key));
    parts.push(`${op.away_team} vs ${op.home_team}`);
    parts.push(`${marketLabel(op)} ${op.raw && "outcome_name" in op.raw ? op.raw.outcome_name : ""}`.trim());
    const offered = effOp.legs.find(l => l.role === "offered" || l.role === "a");
    if (offered) {
      const info = bookInfo(offered.book);
      parts.push(`@ ${formatAmerican(offered.price_american)} ${info.name}`);
    }
    if (op.mode === "ev") {
      const ev = overrideEvPct ?? op.edge_pct;
      parts.push(`EV ${ev >= 0 ? "+" : ""}${ev.toFixed(2)}%`);
      parts.push(`Fair ${formatAmerican(op.raw.fair_price_american)}`);
    } else if (op.mode === "profit_boost") {
      parts.push(`Conv ${op.raw.conversion_pct.toFixed(2)}% @ ${op.raw.boost_pct}% boost`);
      parts.push(
        `Boost ${formatAmerican(op.raw.boost_leg.original_price_american)} → ${formatAmerican(op.raw.boost_leg.boosted_price_american)} on ${op.raw.boost_leg.book}`,
      );
      parts.push(`Hedge ${formatAmerican(op.raw.hedge_leg.price_american)} on ${op.raw.hedge_leg.book}`);
      parts.push(`Hold ${op.raw.hold_pct >= 0 ? "+" : ""}${op.raw.hold_pct.toFixed(2)}%`);
    } else if (op.mode === "arb") {
      parts.push(`ROI +${op.raw.roi_pct.toFixed(2)}%`);
    } else if (op.mode === "low_hold") {
      parts.push(`Hold ${op.raw.hold_pct.toFixed(2)}%`);
    } else {
      parts.push(`Conv ${op.raw.conversion_pct.toFixed(1)}%`);
    }
    const text = parts.join(" · ");
    try {
      void navigator.clipboard.writeText(text).then(() => setCopied(true), () => {});
    } catch {}
  }, [op, effOp, overrideEvPct]);

  const bookLegs = op.legs
    .map((leg, i) => ({ leg, i }))
    .filter(({ leg }) => leg.role !== "fair");

  const profit = splitLabel(math.profit_label);
  const profitTitle =
    op.mode === "ev" ? "Expected value" : op.mode === "low_hold" ? "Hedged result" : "Locked profit";
  // Low hold usually costs a little — it's a result, not an edge to act on.
  const profitTone = op.mode === "low_hold" ? "text-text-1" : "text-edge";

  return (
    <div className="flex flex-col gap-4 bg-bg-1 px-4 py-4">
      {/* Stake tiles */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {bookLegs.map(({ leg, i }) => {
          const s = splitLabel(math.legs[i]?.stake_label ?? "");
          return (
            <div key={i} className="rounded-lg border border-border-subtle bg-bg-0 px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className={LABEL}>{legRoleLabel(op, leg, i)}</span>
                <span className="inline-flex items-center gap-1.5 text-[length:var(--fs-12)] text-text-2">
                  <BookLogo bookKey={leg.book} mode="label" />
                  {bookInfo(leg.book).name}
                </span>
              </div>
              <div className="mt-1 truncate text-[length:var(--fs-13)] text-text-1">
                {formatOutcomeLabel(leg.outcome_name, op.market_kind, leg.point)}{" "}
                <span className="text-text-3">at</span>{" "}
                {op.mode === "ev" && leg.role === "offered" ? (
                  <input
                    type="text"
                    inputMode="numeric"
                    value={priceDraft}
                    placeholder={formatAmerican(leg.price_american)}
                    onChange={e => setPriceDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Escape") setPriceDraft("");
                    }}
                    aria-label="Override the book's price"
                    title="Price moved? Type the book's current price to re-size Kelly. Esc resets."
                    className={clsx(
                      "tabular w-16 rounded border bg-bg-2 px-1.5 py-0.5 font-semibold text-text-1 outline-none placeholder:text-text-1",
                      overridePrice != null
                        ? "border-text-3"
                        : priceDraft
                          ? "border-stale"
                          : "border-border-subtle hover:border-text-3",
                    )}
                  />
                ) : (
                  <span className="tabular font-semibold">{formatAmerican(leg.price_american)}</span>
                )}
              </div>
              {op.mode === "ev" && leg.role === "offered" && overridePrice != null && overrideEvPct != null && (
                <div className="mt-1 flex items-center gap-2 text-[length:var(--fs-12)] text-text-3">
                  <span>
                    Was <span className="tabular">{formatAmerican(op.raw.offered_price_american)}</span> · EV{" "}
                    <span className={clsx("tabular", overrideEvPct > 0 ? "text-edge" : "text-stale")}>
                      {overrideEvPct >= 0 ? "+" : ""}
                      {overrideEvPct.toFixed(2)}%
                    </span>
                    {overrideEvPct <= 0 && " — no bet"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPriceDraft("")}
                    className="text-text-2 underline-offset-2 hover:text-text-1 hover:underline"
                  >
                    Reset
                  </button>
                </div>
              )}
              <div className="tabular mt-2 text-[length:var(--fs-22)] font-semibold leading-[var(--lh-22)] text-text-1">
                {s.amount}
              </div>
              {s.rest && <div className="mt-0.5 text-[length:var(--fs-12)] text-text-3">{s.rest}</div>}
            </div>
          );
        })}
        <div
          className={clsx(
            "rounded-lg border px-4 py-3",
            op.mode === "low_hold"
              ? "border-border-subtle bg-bg-0"
              : "border-[var(--edge-25)] bg-[var(--edge-10)]",
          )}
        >
          <span className={LABEL}>{profitTitle}</span>
          <div
            className={clsx(
              "tabular mt-1 text-[length:var(--fs-22)] font-semibold leading-[var(--lh-22)]",
              profitTone,
            )}
          >
            {profit.amount}
          </div>
          {profit.rest && <div className="mt-0.5 text-[length:var(--fs-12)] text-text-2">{profit.rest}</div>}
          <div className="mt-2 text-[length:var(--fs-12)] text-text-3">
            Total stake <span className="tabular text-text-2">{math.primary_stake_label}</span>
          </div>
        </div>
      </div>

      {/* Sizing controls + context */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className="flex items-center gap-2">
          <span className={LABEL}>Bankroll</span>
          <span className="flex h-8 items-center gap-1 rounded-md border border-border-subtle bg-bg-2 px-2">
            <span className="tabular text-[length:var(--fs-13)] text-text-3">$</span>
            <input
              type="number"
              value={bankroll}
              onChange={e => persistBankroll(clamp(Number(e.target.value) || 0, 10, 10_000_000))}
              min={10}
              step={50}
              className="tabular w-24 bg-transparent text-[length:var(--fs-13)] text-text-1 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
          </span>
        </label>

        {op.mode === "ev" && (
          <label className="flex items-center gap-2">
            <span className={LABEL}>Kelly fraction</span>
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={kellyFrac}
              onChange={e => persistKelly(Number(e.target.value))}
              className="w-28 accent-text-1"
            />
            <span className="tabular w-12 text-[length:var(--fs-13)] text-text-1">{kellyFrac.toFixed(2)}×</span>
          </label>
        )}

        <div className="flex items-center gap-2">
          <span className={LABEL}>Round to</span>
          <Segmented<string>
            size="sm"
            ariaLabel="Round stakes to"
            value={String(rounding)}
            onChange={v => persistRound(Number(v) as RoundIncrement)}
            options={ROUND_OPTIONS.map(r => ({
              value: String(r),
              label: <span className="tabular">${r}</span>,
            }))}
          />
        </div>

        {op.mode === "ev" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[length:var(--fs-12)] text-text-3">
            <span className="inline-flex items-center gap-1.5">
              Fair <span className="tabular text-text-1">{formatAmerican(op.raw.fair_price_american)}</span>
              {op.anchor === "pinnacle" ? (
                <Chip tone="sharp" title="Pinnacle no-vig price">Pinnacle</Chip>
              ) : (
                <Chip title="De-vigged consensus">
                  Consensus of <span className="tabular">{op.raw.anchor_book_count}</span> books
                </Chip>
              )}
            </span>
            <span className={clsx(op.stale && "text-stale")}>
              Price <span className="tabular">{formatAgeShort(op.row_age_s)}</span> old
            </span>
            {op.raw.anchor_age_s != null && (
              <span className={clsx(op.raw.reference_delayed && "text-stale")}>
                Fair price <span className="tabular">{formatAgeShort(op.raw.anchor_age_s)}</span> old
                {op.raw.reference_delayed ? ", recheck before betting" : ""}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Book actions */}
      <div className="flex flex-wrap items-center gap-2">
        {bookLegs.map(({ leg, i }) => {
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
              title={disabled ? "No deeplink configured for this book. Open it manually." : `Open the bet slip at ${info.name}`}
              onClick={e => {
                if (disabled) e.preventDefault();
              }}
              className={clsx(
                "inline-flex h-8 items-center gap-2 rounded-md border px-3 text-[length:var(--fs-13)] font-medium transition-colors",
                disabled
                  ? "cursor-not-allowed border-border-subtle bg-bg-1 text-text-3"
                  : "border-border-subtle bg-bg-2 text-text-1 hover:border-text-3",
              )}
            >
              <BookLogo bookKey={leg.book} mode="label" />
              Open {info.name}
              <ExternalLink size={12} aria-hidden />
            </a>
          );
        })}
        <button
          type="button"
          onClick={handleCopy}
          title="Copy a text summary of these legs to your clipboard."
          className="inline-flex h-8 items-center gap-2 rounded-md border border-border-subtle bg-bg-1 px-3 text-[length:var(--fs-13)] font-medium text-text-2 transition-colors hover:text-text-1"
        >
          {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
          {copied ? "Copied" : "Copy legs"}
        </button>
        <span className="ml-auto text-[length:var(--fs-12)] text-text-3" title={new Date(op.commence_time).toString()}>
          Starts{" "}
          <span className="tabular text-text-2">
            {new Date(op.commence_time).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
            })}
          </span>
        </span>
      </div>
    </div>
  );
}
