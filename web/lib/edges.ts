/**
 * Unified edges model.
 *
 * Arb / Low-Hold / +EV / Free-Bet opportunities have different field
 * shapes (two-leg vs single-leg, ROI vs hold vs EV vs conversion). This
 * module flattens them into a discriminated union with a shared envelope
 * — hoisted sortable fields + a `legs: EdgeLeg[]` list + a mode-specific
 * `raw` payload that workbench panels read for mode-specific math.
 *
 * The shared envelope keeps the rendering loop branch-light: the table
 * renderer only consults `mode` for the colored mode chip + the EDGE %
 * label; every other column reads flattened fields.
 */
import type {
  ArbOpportunity,
  EVOpportunity,
  FreeBetOpportunity,
  LowHoldOpportunity,
} from "@/lib/api";

export type EdgeMode = "arb" | "low_hold" | "ev" | "free_bet";

export const EDGE_MODES: readonly EdgeMode[] = [
  "arb",
  "low_hold",
  "ev",
  "free_bet",
] as const;

export const MODE_LABEL: Record<EdgeMode, string> = {
  arb: "ARB",
  low_hold: "LH",
  ev: "EV",
  free_bet: "FB",
};

export const MODE_LONG_LABEL: Record<EdgeMode, string> = {
  arb: "Arbitrage",
  low_hold: "Low Hold",
  ev: "+EV",
  free_bet: "Free Bet",
};

/** One priced leg — one or two per opportunity. */
export interface EdgeLeg {
  book: string;
  outcome_name: string;
  price_american: number;
  point?: number | null;
  /**
   * Role of this leg within the opportunity. `offered` is the EV /
   * free-bet-cash side; `hedge` is the hedging book; `fair` is the
   * Pinnacle/consensus de-vigged reference (EV only); `a`/`b` are the
   * two legs of a two-way arb or low-hold pair.
   */
  role: "a" | "b" | "offered" | "hedge" | "fair";
  /** Stake share (arb/LH legs, 0-1). EV/FB derive this in stake-calc. */
  stake_pct?: number;
}

/** Shared envelope across all modes. */
interface EdgeBase {
  /** Stable key for row identity + workbench expansion state. */
  row_key: string;
  sport_key: string;
  event_id: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  market_kind: string;
  point?: number | null;
  /**
   * Unified signed % edge, positive = profitable. Used for sort + color.
   *  - arb:       roi_pct          (e.g. 1.85 → "+1.85%")
   *  - low_hold:  -hold_pct        (negative hold is effectively a small edge)
   *  - ev:        ev_pct           (e.g. 3.2 → "+3.2%")
   *  - free_bet:  conversion_pct - 100 (e.g. 82% conv → -18%? No — map so
   *                higher conversion reads as higher edge. We use the
   *                dollar expected value per $100 free-bet face, which is
   *                conversion_pct - 100 → wrong sign intuition. Instead:
   *                edge_pct = conversion_pct (free bets are positive by
   *                definition; sort pulls highest conversion to the top.))
   */
  edge_pct: number;
  /** Books involved, sorted for stable key. */
  legs: EdgeLeg[];
  /** Row age in seconds (max leg age across legs). 0 if unknown. */
  row_age_s: number;
  /** STALE flag — row_age_s > 120. */
  stale: boolean;
  /** ARB-overlap flag (EV only today, but surfaced cross-mode). */
  also_in_arb: boolean;
  /** SUS flag (EV confidence=low; extendable). */
  suspicious: boolean;
  /** Sharp anchor (EV only): 'pinnacle' | 'consensus' | null. */
  anchor: "pinnacle" | "consensus" | null;
}

export type EdgeOpportunity =
  | (EdgeBase & { mode: "arb"; raw: ArbOpportunity })
  | (EdgeBase & { mode: "low_hold"; raw: LowHoldOpportunity })
  | (EdgeBase & { mode: "ev"; raw: EVOpportunity })
  | (EdgeBase & { mode: "free_bet"; raw: FreeBetOpportunity });

// ───────────────────────── merge functions ─────────────────────────

function bookPairKey(legs: EdgeLeg[]): string {
  return legs.map(l => l.book).sort().join("+");
}

export function fromArb(op: ArbOpportunity, idx: number): EdgeOpportunity {
  const legs: EdgeLeg[] = op.sides.map((s, i) => ({
    book: s.book,
    outcome_name: s.outcome_name,
    price_american: s.price_american,
    point: s.point,
    role: i === 0 ? "a" : "b",
    stake_pct: s.stake_pct,
  }));
  return {
    mode: "arb",
    raw: op,
    row_key: `arb_${op.event_id}_${op.market_kind}_${op.point ?? "na"}_${bookPairKey(legs)}_${idx}`,
    sport_key: op.sport_key,
    event_id: op.event_id,
    home_team: op.home_team,
    away_team: op.away_team,
    commence_time: op.commence_time,
    market_kind: op.market_kind,
    point: op.point,
    edge_pct: op.roi_pct,
    legs,
    row_age_s: 0,
    stale: false,
    also_in_arb: true,
    suspicious: false,
    anchor: null,
  };
}

export function fromLowHold(
  op: LowHoldOpportunity,
  idx: number,
): EdgeOpportunity {
  const legs: EdgeLeg[] = op.sides.map((s, i) => ({
    book: s.book,
    outcome_name: s.outcome_name,
    price_american: s.price_american,
    point: s.point,
    role: i === 0 ? "a" : "b",
  }));
  return {
    mode: "low_hold",
    raw: op,
    row_key: `lh_${op.event_id}_${op.market_kind}_${op.point ?? "na"}_${bookPairKey(legs)}_${idx}`,
    sport_key: op.sport_key,
    event_id: op.event_id,
    home_team: op.home_team,
    away_team: op.away_team,
    commence_time: op.commence_time,
    market_kind: op.market_kind,
    point: op.point,
    // Surface hold as a (typically negative) edge-equivalent — lower hold
    // ranks higher. Negating turns "0.5% hold" into "−0.5% edge", and
    // sort-desc still floats the best (most-negative) pairs to the top.
    // UI formats this separately so the sign doesn't confuse the user.
    edge_pct: -op.hold_pct,
    legs,
    row_age_s: 0,
    stale: false,
    also_in_arb: false,
    suspicious: false,
    anchor: null,
  };
}

export function fromEv(op: EVOpportunity, idx: number): EdgeOpportunity {
  const legs: EdgeLeg[] = [
    {
      book: op.book,
      outcome_name: op.outcome_name,
      price_american: op.offered_price_american,
      point: op.point,
      role: "offered",
    },
    // Fair / anchor leg — not a bookable side, shown as reference in the
    // workbench and in the table's FAIR column.
    {
      book: op.source === "pinnacle" ? "pinnacle" : "consensus",
      outcome_name: op.outcome_name,
      price_american: op.fair_price_american,
      point: op.point,
      role: "fair",
    },
  ];
  const isStale = op.offered_age_s > 120;
  return {
    mode: "ev",
    raw: op,
    row_key: `ev_${op.event_id}_${op.market_kind}_${op.point ?? "na"}_${op.outcome_name}_${op.book}_${idx}`,
    sport_key: op.sport_key,
    event_id: op.event_id,
    home_team: op.home_team,
    away_team: op.away_team,
    commence_time: op.commence_time,
    market_kind: op.market_kind,
    point: op.point,
    edge_pct: op.ev_pct,
    legs,
    row_age_s: op.offered_age_s,
    stale: isStale,
    also_in_arb: op.also_in_arb,
    suspicious: op.confidence === "low",
    anchor: op.source,
  };
}

export function fromFreeBet(
  op: FreeBetOpportunity,
  idx: number,
): EdgeOpportunity {
  const legs: EdgeLeg[] = [
    {
      book: op.free_leg.book,
      outcome_name: op.free_leg.outcome_name,
      price_american: op.free_leg.price_american,
      point: op.free_leg.point,
      role: "offered",
    },
    {
      book: op.hedge_leg.book,
      outcome_name: op.hedge_leg.outcome_name,
      price_american: op.hedge_leg.price_american,
      point: op.hedge_leg.point,
      role: "hedge",
    },
  ];
  return {
    mode: "free_bet",
    raw: op,
    row_key: `fb_${op.event_id}_${op.market_kind}_${op.point ?? "na"}_${op.free_leg.book}+${op.hedge_leg.book}_${idx}`,
    sport_key: op.sport_key,
    event_id: op.event_id,
    home_team: op.home_team,
    away_team: op.away_team,
    commence_time: op.commence_time,
    market_kind: op.market_kind,
    point: op.point,
    // Higher conversion % ⇒ higher edge. Use the conversion directly
    // (already 0-100) so the sort doesn't require an EV-relative
    // normalisation against offered odds. This keeps free-bet rows
    // sortable among themselves; cross-mode sort groups them as
    // always-positive edges.
    edge_pct: op.conversion_pct,
    legs,
    row_age_s: 0,
    stale: false,
    also_in_arb: false,
    suspicious: false,
    anchor: null,
  };
}

/**
 * Merge the four scanner payloads into one list. Each input is
 * optional — the page can partially render while some SWR keys are
 * still loading.
 */
export function mergeEdges(parts: {
  arb?: ArbOpportunity[];
  lowHold?: LowHoldOpportunity[];
  ev?: EVOpportunity[];
  freeBet?: FreeBetOpportunity[];
}): EdgeOpportunity[] {
  const out: EdgeOpportunity[] = [];
  parts.arb?.forEach((op, i) => out.push(fromArb(op, i)));
  parts.lowHold?.forEach((op, i) => out.push(fromLowHold(op, i)));
  parts.ev?.forEach((op, i) => out.push(fromEv(op, i)));
  parts.freeBet?.forEach((op, i) => out.push(fromFreeBet(op, i)));
  return out;
}

// ─────────────────────── display helpers ──────────────────────────

/**
 * Pretty-print the edge % per mode. Sort uses the unified `edge_pct`
 * but the user still reads the native per-mode semantic.
 */
export function formatEdgePct(op: EdgeOpportunity): string {
  switch (op.mode) {
    case "arb":
      return `${op.raw.roi_pct >= 0 ? "+" : ""}${op.raw.roi_pct.toFixed(2)}%`;
    case "low_hold":
      return `${op.raw.hold_pct.toFixed(2)}%`;
    case "ev":
      return `${op.raw.ev_pct >= 0 ? "+" : ""}${op.raw.ev_pct.toFixed(2)}%`;
    case "free_bet":
      return `${op.raw.conversion_pct.toFixed(1)}%`;
  }
}

/** Short market label with period annotations. */
export function marketLabel(op: EdgeOpportunity): string {
  const mk = op.market_kind;
  if (mk === "h2h" || mk === "h2h_3_way") return "Moneyline";
  if (mk === "totals") return op.point != null ? `Total ${op.point}` : "Total";
  if (mk === "alternate_totals")
    return op.point != null ? `Alt Total ${op.point}` : "Alt Total";
  if (mk === "spreads")
    return op.point != null ? `Spread ±${Math.abs(op.point)}` : "Spread";
  if (mk === "alternate_spreads")
    return op.point != null ? `Alt Spread ±${Math.abs(op.point)}` : "Alt Spread";
  if (mk === "team_totals")
    return op.point != null ? `Team Total ${op.point}` : "Team Total";
  if (mk === "alternate_team_totals")
    return op.point != null ? `Alt Team Total ${op.point}` : "Alt Team Total";
  if (/_h[12]$/.test(mk)) return mk.replace(/_h([12])$/, " (H$1)");
  if (/_q[1-4]$/.test(mk)) return mk.replace(/_q([1-4])$/, " (Q$1)");
  if (/_p[1-3]$/.test(mk)) return mk.replace(/_p([1-3])$/, " (P$1)");
  if (/_1st_5_innings$/.test(mk)) return mk.replace(/_1st_5_innings$/, " (F5)");
  return mk;
}

/** Side-column label for single-leg modes (EV, FB offered leg). */
export function sideLabel(op: EdgeOpportunity): string {
  if (op.mode === "ev") {
    if (op.market_kind === "spreads" || op.market_kind === "alternate_spreads") {
      const sign = op.point != null && op.point > 0 ? "+" : "";
      return op.point != null
        ? `${op.raw.outcome_name} ${sign}${op.point}`
        : op.raw.outcome_name;
    }
    return op.raw.outcome_name;
  }
  if (op.mode === "free_bet") return op.raw.free_leg.outcome_name;
  return op.legs[0]?.outcome_name ?? "";
}

/** Time-to-commence label. Returns "LIVE" if commence_time is past. */
export function commenceLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffH = (d.getTime() - now.getTime()) / 3_600_000;
  if (diffH < 0) return "LIVE";
  if (diffH < 1) return `${Math.round(diffH * 60)}m`;
  if (diffH < 24) return `${Math.round(diffH)}h`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Color utility for edge magnitude. */
export function edgeColor(op: EdgeOpportunity): string {
  if (op.mode === "low_hold") {
    const h = op.raw.hold_pct;
    if (h < 0.5) return "text-price-up";
    if (h < 1.5) return "text-accent";
    if (h < 2.5) return "text-flash";
    return "text-text-2";
  }
  if (op.mode === "free_bet") {
    const c = op.raw.conversion_pct;
    if (c >= 80) return "text-price-up";
    if (c >= 70) return "text-accent";
    if (c >= 60) return "text-flash";
    return "text-text-2";
  }
  // arb / ev — both positive-is-good %
  const pct = op.edge_pct;
  if (pct >= 5) return "text-price-up";
  if (pct >= 2) return "text-accent";
  if (pct >= 1) return "text-flash";
  return "text-text-2";
}

// ─────────────────────── sort helpers ────────────────────────────

export type SortKey =
  | "edge"
  | "mode"
  | "sport"
  | "event"
  | "market"
  | "commence";
export type SortDir = "asc" | "desc";

export function sortEdges(
  rows: EdgeOpportunity[],
  key: SortKey,
  dir: SortDir,
): EdgeOpportunity[] {
  const sign = dir === "asc" ? 1 : -1;
  const arr = [...rows];
  arr.sort((a, b) => {
    let av: number | string;
    let bv: number | string;
    switch (key) {
      case "edge":
        // For sort: arb/ev/fb → higher is better; low_hold uses -hold so
        // higher is also better. The unified edge_pct already encodes
        // this. Free-bet's conversion % lives on a different absolute
        // scale (60-95) vs arb/ev (1-5) — a pure desc sort will always
        // float free bets first. That's intended: FB edges are
        // risk-free EV-positive by construction.
        av = a.edge_pct;
        bv = b.edge_pct;
        break;
      case "mode":
        av = a.mode;
        bv = b.mode;
        break;
      case "sport":
        av = a.sport_key;
        bv = b.sport_key;
        break;
      case "event":
        av = `${a.away_team}@${a.home_team}`;
        bv = `${b.away_team}@${b.home_team}`;
        break;
      case "market":
        av = a.market_kind;
        bv = b.market_kind;
        break;
      case "commence":
        av = new Date(a.commence_time).getTime();
        bv = new Date(b.commence_time).getTime();
        break;
    }
    if (typeof av === "number" && typeof bv === "number") {
      return sign * (av - bv);
    }
    return sign * String(av).localeCompare(String(bv));
  });
  return arr;
}
