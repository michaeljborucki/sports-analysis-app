"use client";
import { Fragment, memo, useMemo } from "react";
import clsx from "clsx";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  ChevronRightIcon,
} from "lucide-react";

import { BookLogo } from "@/components/book-logo";
import { AnimatedPrice } from "@/components/animated-price";
import { Chip, EdgeBar, formatAgeShort } from "@/components/ui";
import { formatAmerican } from "@/lib/format";
import { bookInfo } from "@/lib/books";
import {
  type EdgeMode,
  type EdgeOpportunity,
  type SortDir,
  type SortKey,
  commenceClock,
  commenceLabel,
  formatEdgePct,
  formatOutcomeLabel,
  marketLabel,
  NOVIG_MAKER,
  sideLabel,
  usesMakerPrice,
} from "@/lib/edges";
import { SPORTS, type SportKey } from "@/lib/sports";
import { useEdgesPrefs } from "@/lib/use-edges-prefs";
import { kellyStake, roundStake } from "@/lib/stake-calc";

import { Workbench } from "./workbench";
import { MODE_NAME } from "./mode-toggle";

/**
 * Low-hold scan threshold (matches the `apiPaths.lowHold(..., 2.5, ...)`
 * request on the page). LH edge_pct is −hold, so nearly every row is
 * negative; the bar shows headroom under the threshold instead so the
 * tightest pairs read as the biggest bars. Display only.
 */
const LOW_HOLD_THRESHOLD = 2.5;

function barValue(op: EdgeOpportunity): number {
  return op.mode === "low_hold" ? LOW_HOLD_THRESHOLD + op.edge_pct : op.edge_pct;
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

/** Plain-language staleness note for a row, or null when fresh. */
function staleNote(op: EdgeOpportunity): string | null {
  if (op.stale) return `price ${formatAgeShort(op.row_age_s)} old`;
  if (op.mode === "ev" && op.raw.reference_delayed && op.raw.anchor_age_s != null) {
    return `fair price ${Math.ceil(op.raw.anchor_age_s / 60)}m old, recheck`;
  }
  return null;
}

/** Leg column headers per mode (single-mode view). */
const LEG_HEADERS: Record<EdgeMode, [string, string]> = {
  arb: ["Leg one", "Leg two"],
  low_hold: ["Leg one", "Leg two"],
  ev: ["Side", "Fair price"],
  free_bet: ["Free bet", "Hedge"],
  profit_boost: ["Boosted leg", "Hedge"],
};

interface HeaderProps {
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}

function SortButton({
  label,
  colKey,
  sortKey,
  sortDir,
  onSort,
  className,
}: { label: string; colKey: SortKey; className?: string } & HeaderProps) {
  const active = colKey === sortKey;
  const ArrowIcon = !active ? null : sortDir === "asc" ? ArrowUpIcon : ArrowDownIcon;
  return (
    <button
      type="button"
      onClick={() => onSort(colKey)}
      className={clsx(
        "inline-flex items-center gap-1 select-none hover:text-text-1",
        active && "text-text-1",
        className,
      )}
    >
      {label}
      {ArrowIcon && <ArrowIcon size={11} aria-hidden className="text-text-3" />}
    </button>
  );
}

function Th({
  children,
  align = "left",
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th className={clsx("dt-th", align === "right" && "text-right", className)}>{children}</th>
  );
}

export function EdgesTable({
  rows,
  expanded,
  onToggleExpand,
  stake,
  sortKey,
  sortDir,
  onSort,
  showMaker = false,
}: {
  rows: EdgeOpportunity[];
  expanded: Set<string>;
  onToggleExpand: (key: string) => void;
  stake: number;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  /** "Take + maker" toggle: show each Novig leg's other price. */
  showMaker?: boolean;
}) {
  const hdr: HeaderProps = { sortKey, sortDir, onSort };

  // One pass: bar scale (max edge among visible rows) + which modes are
  // present (modes are single-select today, so the Mode column hides).
  const { maxBar, modes } = useMemo(() => {
    let max = 0;
    const seen = new Set<EdgeMode>();
    for (const op of rows) {
      const v = barValue(op);
      if (v > max) max = v;
      seen.add(op.mode);
    }
    return { maxBar: max, modes: seen };
  }, [rows]);
  const showMode = modes.size > 1;
  const legHeaders: [string, string] =
    modes.size === 1 ? LEG_HEADERS[[...modes][0]] : ["Leg one", "Leg two"];
  const colCount = showMode ? 10 : 9;

  // Sorted by Starts, rows arrive grouped by game (see sortEdges), so a
  // header goes above each game's first row.
  const grouped = sortKey === "commence";
  const gameCounts = useMemo(() => {
    if (!grouped) return null;
    const counts = new Map<string, number>();
    for (const op of rows) counts.set(op.event_id, (counts.get(op.event_id) ?? 0) + 1);
    return counts;
  }, [rows, grouped]);

  return (
    <div className="overflow-x-auto rounded-lg border border-border-subtle bg-bg-0">
      <table className="w-full border-collapse">
        <thead className="dt-head">
          <tr>
            <th className="dt-th w-8" aria-label="Expand" />
            <Th className="w-[120px]">
              <SortButton label="Edge" colKey="edge" {...hdr} />
            </Th>
            {showMode && (
              <Th className="w-[96px]">
                <SortButton label="Mode" colKey="mode" {...hdr} />
              </Th>
            )}
            <Th>
              <span className="inline-flex items-center gap-3">
                <SortButton label="Event" colKey="event" {...hdr} />
                <SortButton label="Sport" colKey="sport" {...hdr} />
              </span>
            </Th>
            <Th>
              <SortButton label="Market" colKey="market" {...hdr} />
            </Th>
            <Th>{legHeaders[0]}</Th>
            <Th>{legHeaders[1]}</Th>
            <Th align="right">Stake</Th>
            <Th align="right">
              <SortButton label="Starts" colKey="commence" {...hdr} />
            </Th>
          </tr>
        </thead>
        <tbody>
          {/* Memo'd rows + flat map. If row counts regularly exceed a few
              thousand, consider virtualization (not added: new dep). */}
          {rows.map((op, i) => (
            <Fragment key={op.row_key}>
              {gameCounts && (i === 0 || rows[i - 1].event_id !== op.event_id) && (
                <GameHeader op={op} count={gameCounts.get(op.event_id) ?? 0} colCount={colCount} />
              )}
              <EdgeRow
                op={op}
                open={expanded.has(op.row_key)}
                stake={stake}
                maxBar={maxBar}
                showMode={showMode}
                colCount={colCount}
                onToggleExpand={onToggleExpand}
                showMaker={showMaker}
              />
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Divider row above a game's edges when the table is sorted by Starts. */
function GameHeader({
  op,
  count,
  colCount,
}: {
  op: EdgeOpportunity;
  count: number;
  colCount: number;
}) {
  const live = commenceLabel(op.commence_time) === "LIVE";
  return (
    <tr className="border-b border-border-subtle bg-bg-1">
      <td colSpan={colCount} className="dt-td py-1.5">
        <span className="flex items-center gap-2 whitespace-nowrap text-[length:var(--fs-12)]">
          <span className="font-medium text-text-1">
            {op.away_team} @ {op.home_team}
          </span>
          <span className="text-text-3">{sportLabel(op.sport_key)}</span>
          <span className="text-text-3">·</span>
          {live ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-live">
              <span className="live-dot" aria-hidden />
              Live
            </span>
          ) : (
            <span className="tabular text-text-2">{commenceClock(op.commence_time)}</span>
          )}
          <span className="text-text-3">·</span>
          <span className="tabular text-text-3">
            {count} {count === 1 ? "edge" : "edges"}
          </span>
        </span>
      </td>
    </tr>
  );
}

function BookTag({ book }: { book: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-text-2">
      <BookLogo bookKey={book} mode="label" />
      <span className="whitespace-nowrap">{bookInfo(book).name}</span>
    </span>
  );
}

/**
 * The other Novig price for this outcome: on a take leg, the maker price
 * you could post instead; on a maker leg, what taking costs right now.
 */
function Counterpart({ book, price }: { book: string; price?: number | null }) {
  if (price == null) return null;
  const maker = book === NOVIG_MAKER;
  return (
    <span
      className="text-[length:var(--fs-12)] text-text-3"
      title={
        maker
          ? "Price to take this side on Novig right now"
          : "Price to post on Novig: one tick above the best bid (or joining it on a one-tick spread)"
      }
    >
      {maker ? "take" : "make"} <span className="tabular">{formatAmerican(price)}</span>
    </span>
  );
}

/** Side text, price, then book — one leg on one line. */
function Leg({
  side,
  price,
  book,
  from,
  note,
  counterpart,
}: {
  side: string;
  price: number;
  book: string;
  /** Pre-boost price, shown struck through before the boosted one. */
  from?: number;
  note?: React.ReactNode;
  /** Novig take/maker pairing; rendered only when provided. */
  counterpart?: number | null;
}) {
  return (
    <span className="flex min-w-0 items-center gap-2 whitespace-nowrap">
      <span className="max-w-[180px] truncate text-text-1" title={side}>
        {side}
      </span>
      {from != null && (
        <span className="tabular text-text-3 line-through">{formatAmerican(from)}</span>
      )}
      <span className="tabular font-semibold text-text-1">{formatAmerican(price)}</span>
      <BookTag book={book} />
      {counterpart !== undefined && <Counterpart book={book} price={counterpart} />}
      {note}
    </span>
  );
}

/**
 * One row in the edges table. Memoised so toggling `expanded` for one row
 * only re-renders that row. `onToggleExpand` must stay referentially
 * stable (it's a useCallback on the page) or the memo becomes a no-op.
 */
const EdgeRow = memo(function EdgeRow({
  op,
  open,
  stake,
  maxBar,
  showMode,
  colCount,
  onToggleExpand,
  showMaker,
}: {
  op: EdgeOpportunity;
  open: boolean;
  stake: number;
  maxBar: number;
  showMode: boolean;
  colCount: number;
  onToggleExpand: (key: string) => void;
  showMaker: boolean;
}) {
  const note = staleNote(op);
  const counterpartOf = (leg: { counterpart_price_american?: number | null } | undefined) =>
    showMaker ? (leg?.counterpart_price_american ?? null) : undefined;
  const isStale = note != null;
  const starts = commenceLabel(op.commence_time);

  let legOne: React.ReactNode = null;
  let legTwo: React.ReactNode = null;
  const depth = (d: number | null | undefined) =>
    d != null ? (
      <span className="text-[length:var(--fs-12)] text-text-3" title="Top-of-book depth at this price">
        max <span className="tabular">${d.toFixed(0)}</span>
      </span>
    ) : null;
  if (op.mode === "arb" || op.mode === "low_hold") {
    const [a, b] = op.legs;
    if (a)
      legOne = (
        <Leg
          side={formatOutcomeLabel(a.outcome_name, op.market_kind, a.point)}
          price={a.price_american}
          book={a.book}
          note={depth(a.max_stake_dollars)}
          counterpart={counterpartOf(a)}
        />
      );
    if (b)
      legTwo = (
        <Leg
          side={formatOutcomeLabel(b.outcome_name, op.market_kind, b.point)}
          price={b.price_american}
          book={b.book}
          note={depth(b.max_stake_dollars)}
          counterpart={counterpartOf(b)}
        />
      );
  } else if (op.mode === "ev") {
    legOne = (
      <Leg
        side={sideLabel(op)}
        price={op.raw.offered_price_american}
        book={op.raw.book}
        note={depth(op.raw.max_stake_dollars)}
        counterpart={counterpartOf(op.legs[0])}
      />
    );
    const pin = op.anchor === "pinnacle";
    legTwo = (
      <span className="flex items-center gap-2 whitespace-nowrap">
        <span className="tabular text-text-1">{formatAmerican(op.raw.fair_price_american)}</span>
        <Chip
          tone={pin ? "sharp" : "neutral"}
          title={pin ? "Pinnacle no-vig price" : `Consensus of ${op.raw.anchor_book_count} books`}
        >
          {pin ? "Pinnacle" : "Consensus"}
        </Chip>
        {op.raw.anchor_age_s != null && !op.raw.reference_delayed && (
          <span
            className="text-[length:var(--fs-12)] text-text-3"
            title={`Oldest comparison quote: ${op.raw.anchor_age_s}s. Offer age: ${op.raw.offered_age_s}s.`}
          >
            <span className="tabular">{Math.ceil(op.raw.anchor_age_s / 60)}m</span> old
          </span>
        )}
      </span>
    );
  } else if (op.mode === "profit_boost") {
    legOne = (
      <Leg
        side={formatOutcomeLabel(op.raw.boost_leg.outcome_name, op.market_kind, op.raw.boost_leg.point)}
        from={op.raw.boost_leg.original_price_american}
        price={op.raw.boost_leg.boosted_price_american}
        book={op.raw.boost_leg.book}
      />
    );
    legTwo = (
      <Leg
        side={formatOutcomeLabel(op.raw.hedge_leg.outcome_name, op.market_kind, op.raw.hedge_leg.point)}
        price={op.raw.hedge_leg.price_american}
        book={op.raw.hedge_leg.book}
        counterpart={counterpartOf(op.raw.hedge_leg)}
        note={
          <span
            className="text-[length:var(--fs-12)] text-text-3"
            title="Boosted-pair hold. Negative means locked profit."
          >
            hold <span className="tabular">{op.raw.hold_pct >= 0 ? "+" : ""}{op.raw.hold_pct.toFixed(2)}%</span>
          </span>
        }
      />
    );
  } else if (op.mode === "free_bet") {
    legOne = (
      <Leg
        side={formatOutcomeLabel(op.raw.free_leg.outcome_name, op.market_kind, op.raw.free_leg.point)}
        price={op.raw.free_leg.price_american}
        book={op.raw.free_leg.book}
      />
    );
    legTwo = (
      <Leg
        side={formatOutcomeLabel(op.raw.hedge_leg.outcome_name, op.market_kind, op.raw.hedge_leg.point)}
        price={op.raw.hedge_leg.price_american}
        book={op.raw.hedge_leg.book}
        counterpart={counterpartOf(op.raw.hedge_leg)}
      />
    );
  }

  return (
    <Fragment>
      <tr
        className={clsx(
          "dt-row",
          open ? "bg-bg-2" : isStale && "bg-[var(--stale-10)]",
        )}
      >
        <td className="dt-td w-8" style={{ paddingRight: 0 }}>
          <button
            type="button"
            onClick={() => onToggleExpand(op.row_key)}
            aria-expanded={open}
            aria-label={open ? "Collapse workbench" : "Expand workbench"}
            className="inline-flex h-5 w-5 items-center justify-center rounded text-text-3 transition-colors hover:text-text-1"
          >
            {open ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
          </button>
        </td>
        <td className="dt-td">
          <EdgeBar value={barValue(op)} max={maxBar} stale={isStale}>
            <AnimatedPrice value={op.edge_pct}>{formatEdgePct(op)}</AnimatedPrice>
          </EdgeBar>
        </td>
        {showMode && (
          <td className="dt-td">
            <Chip>{MODE_NAME[op.mode]}</Chip>
          </td>
        )}
        <td className="dt-td">
          <span className="flex items-center gap-2 whitespace-nowrap">
            <span className="text-text-1">
              {op.away_team} @ {op.home_team}
            </span>
            <span className="text-[length:var(--fs-12)] text-text-3">{sportLabel(op.sport_key)}</span>
            {usesMakerPrice(op) && (
              <Chip title="Assumes your posted Novig order fills at this price. Nothing is guaranteed until it does.">
                Maker
              </Chip>
            )}
            {op.also_in_arb && op.mode !== "arb" && (
              <Chip title="Also present as an arbitrage pair.">Also an arb</Chip>
            )}
            {op.suspicious && (
              <Chip tone="stale" title="Low-confidence EV. Likely stale or mispriced, verify before betting.">
                Suspicious
              </Chip>
            )}
            {note && <span className="text-[length:var(--fs-12)] text-stale">{note}</span>}
          </span>
        </td>
        <td className="dt-td whitespace-nowrap text-text-2">{marketLabel(op)}</td>
        <td className="dt-td">{legOne}</td>
        <td className="dt-td">{legTwo}</td>
        <td className="dt-td text-right">
          <StakeCell op={op} stake={stake} />
        </td>
        <td className="dt-td whitespace-nowrap text-right">
          {starts === "LIVE" ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-live">
              <span className="live-dot" aria-hidden />
              Live
            </span>
          ) : (
            <span className="tabular text-text-2">{starts}</span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border-subtle">
          <td colSpan={colCount} className="p-0">
            <Workbench op={op} stake={stake} />
          </td>
        </tr>
      )}
    </Fragment>
  );
});

/**
 * Compact per-row stake preview. Same math as the workbench and the page's
 * min-stake filter (`computeRowStakeDollars`), via the shared prefs store.
 *
 * - arb / low_hold: page-level stake input is the total outlay across legs.
 * - ev:             Kelly stake = bankroll × kelly_fraction × Kelly_full.
 * - profit_boost:   boosted-leg stake + hedge.
 * - free_bet:       page-level stake is the free-bet face; shows the cash hedge.
 */
function StakeCell({ op, stake }: { op: EdgeOpportunity; stake: number }) {
  const prefs = useEdgesPrefs();
  let amount: number | null = null;
  if (op.mode === "arb" || op.mode === "low_hold") {
    amount = stake;
  } else if (op.mode === "ev") {
    amount = kellyStake(
      prefs.bankroll,
      op.raw.offered_price_american,
      op.raw.fair_probability,
      prefs.kellyFrac,
      prefs.rounding,
    ).stake;
  } else if (op.mode === "profit_boost") {
    const hedge = roundStake((stake / 100) * op.raw.hedge_stake_per_100_boost, prefs.rounding);
    amount = stake + hedge;
  } else if (op.mode === "free_bet") {
    amount = roundStake((stake / 100) * op.raw.hedge_stake_per_100, prefs.rounding);
  }
  if (amount == null) return <span className="tabular text-text-3">—</span>;
  return <span className="tabular text-text-1">${amount.toLocaleString()}</span>;
}
