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
  ProfitBoostOpportunity,
} from "@/lib/api";

export type EdgeMode = "arb" | "low_hold" | "ev" | "free_bet" | "profit_boost";

export const EDGE_MODES: readonly EdgeMode[] = [
  "arb",
  "low_hold",
  "ev",
  "free_bet",
  "profit_boost",
] as const;

export const MODE_LABEL: Record<EdgeMode, string> = {
  arb: "ARB",
  low_hold: "LH",
  ev: "EV",
  free_bet: "FB",
  profit_boost: "PB",
};

export const MODE_LONG_LABEL: Record<EdgeMode, string> = {
  arb: "Arbitrage",
  low_hold: "Low Hold",
  ev: "+EV",
  free_bet: "Free Bet",
  profit_boost: "Profit Boost",
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
  /** Top-of-book fillable depth in dollars at the displayed price.
   *  Non-null for Kalshi / Polymarket arb legs; null for sportsbooks
   *  (no published depth) and for non-arb modes. */
  max_stake_dollars?: number | null;
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
  | (EdgeBase & { mode: "free_bet"; raw: FreeBetOpportunity })
  | (EdgeBase & { mode: "profit_boost"; raw: ProfitBoostOpportunity });

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
    max_stake_dollars: s.max_stake_dollars ?? null,
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

export function fromProfitBoost(
  op: ProfitBoostOpportunity,
  idx: number,
): EdgeOpportunity {
  // Two-leg conversion shape, mirroring free_bet. Boost leg is "offered"
  // (price shown is the post-boost American line), hedge leg is "hedge".
  const legs: EdgeLeg[] = [
    {
      book: op.boost_leg.book,
      outcome_name: op.boost_leg.outcome_name,
      price_american: op.boost_leg.boosted_price_american,
      point: op.boost_leg.point,
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
    mode: "profit_boost",
    raw: op,
    row_key: `pb_${op.event_id}_${op.market_kind}_${op.point ?? "na"}_${op.boost_leg.book}+${op.hedge_leg.book}_${idx}`,
    sport_key: op.sport_key,
    event_id: op.event_id,
    home_team: op.home_team,
    away_team: op.away_team,
    commence_time: op.commence_time,
    market_kind: op.market_kind,
    point: op.point,
    // Conversion % = unified edge metric. Higher = more locked-in profit.
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
 * Merge the five scanner payloads into one list. Each input is
 * optional — the page can partially render while some SWR keys are
 * still loading.
 */
export function mergeEdges(parts: {
  arb?: ArbOpportunity[];
  lowHold?: LowHoldOpportunity[];
  ev?: EVOpportunity[];
  freeBet?: FreeBetOpportunity[];
  profitBoost?: ProfitBoostOpportunity[];
}): EdgeOpportunity[] {
  const out: EdgeOpportunity[] = [];
  parts.arb?.forEach((op, i) => out.push(fromArb(op, i)));
  parts.lowHold?.forEach((op, i) => out.push(fromLowHold(op, i)));
  parts.ev?.forEach((op, i) => out.push(fromEv(op, i)));
  parts.freeBet?.forEach((op, i) => out.push(fromFreeBet(op, i)));
  parts.profitBoost?.forEach((op, i) => out.push(fromProfitBoost(op, i)));
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
    case "profit_boost":
      // Conversion % is the locked-in profit fraction. Always positive
      // for emitted rows (negative-conversion pairs are filtered out).
      return `${op.raw.conversion_pct.toFixed(2)}%`;
  }
}

/** Decompose a market_key into (family, alt-flag, period suffix label).
 * `spreads_h1`           → { family: "spreads", alt: false, period: " H1" }
 * `alternate_totals_q3`  → { family: "totals", alt: true,  period: " Q3" }
 * `h2h_1st_5_innings`    → { family: "h2h", alt: false, period: " F5" }
 * `team_totals`          → { family: "team_totals", alt: false, period: "" }
 */
function parseMarketKind(mk: string): {
  family: "h2h" | "spreads" | "totals" | "team_totals" | null;
  alt: boolean;
  period: string;
} {
  // Map period suffix tokens (longest first to avoid `_h1` matching inside
  // `_1st_5_innings`).
  const periodMap: ReadonlyArray<readonly [RegExp, string]> = [
    [/_1st_5_innings$/, " F5"],
    [/_(h[12])$/, ""],   // value filled below
    [/_(q[1-4])$/, ""],
    [/_(p[1-3])$/, ""],
  ];
  let period = "";
  let base = mk;
  for (const [re, fixed] of periodMap) {
    const m = base.match(re);
    if (!m) continue;
    period = fixed || ` ${m[1].toUpperCase()}`;
    base = base.slice(0, -m[0].length);
    break;
  }
  let alt = false;
  if (base.startsWith("alternate_")) {
    alt = true;
    base = base.slice("alternate_".length);
  }
  let family: "h2h" | "spreads" | "totals" | "team_totals" | null = null;
  if (base === "h2h" || base === "h2h_3_way") family = "h2h";
  else if (base === "spreads") family = "spreads";
  else if (base === "totals") family = "totals";
  else if (base === "team_totals") family = "team_totals";
  return { family, alt, period };
}

/** Short market label with period annotations. */
export function marketLabel(op: EdgeOpportunity): string {
  const mk = op.market_kind;
  const { family, alt, period } = parseMarketKind(mk);
  if (family === "h2h") return `Moneyline${period}`;
  if (family === "totals") {
    const head = `${alt ? "Alt Total" : "Total"}${period}`;
    return op.point != null ? `${head} ${op.point}` : head;
  }
  if (family === "spreads") {
    const head = `${alt ? "Alt Spread" : "Spread"}${period}`;
    return op.point != null ? `${head} ±${Math.abs(op.point)}` : head;
  }
  if (family === "team_totals") {
    const head = `${alt ? "Alt Team Total" : "Team Total"}${period}`;
    return op.point != null ? `${head} ${op.point}` : head;
  }
  // Player props (player_*, batter_*, pitcher_*): pretty-print the
  // category. The line itself isn't included here — each outcome carries
  // its own number, so the side label is the right place for it
  // (see formatOutcomeLabel).
  if (isPlayerPropMarket(mk)) {
    return formatPlayerPropLabel(mk);
  }
  // Unknown market — surface the raw key so it's at least debuggable.
  return mk;
}

function formatPlayerPropLabel(marketKey: string): string {
  let mk = marketKey;
  let altPrefix = "";
  if (mk.endsWith("_alternate")) {
    altPrefix = "Alt ";
    mk = mk.slice(0, -"_alternate".length);
  }
  // Standard combos get terse labels so the market column doesn't blow
  // out the table width on long stat names.
  const combos: Record<string, string> = {
    // NBA / WNBA / NHL combos
    player_points_rebounds_assists: "Player PRA",
    player_points_rebounds: "Player PR",
    player_points_assists: "Player PA",
    player_rebounds_assists: "Player RA",
    player_double_double: "Player Double Double",
    player_triple_double: "Player Triple Double",
    player_first_basket: "Player First Basket",
    // MLB combos
    batter_hits_runs_rbis: "Batter HRRBI",
    batter_first_home_run: "Batter First HR",
    pitcher_record_a_win: "Pitcher Win",
  };
  if (mk in combos) {
    return `${altPrefix}${combos[mk]}`;
  }
  // Generic: "<role>_<noun>" → "Role Noun"
  //   "player_points"        → "Player Points"
  //   "batter_total_bases"   → "Batter Total Bases"
  //   "pitcher_strikeouts"   → "Pitcher Strikeouts"
  const titled = mk.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return `${altPrefix}${titled}`;
}

/**
 * Player-prop market-key prefixes across all sports we cover. Each book
 * groups player-level props under one of these:
 *
 *   player_*   — NBA, WNBA, NHL, soccer, future NFL/NCAAF
 *   batter_*   — MLB / NCAA Baseball / Asian Baseball / Mexican Baseball
 *   pitcher_*  — same baseball family
 *
 * Outcome names follow `<Player Name> Over` / `<Player Name> Under` (or
 * `<Player Name> Yes` / `<Player Name> No` for binary props like
 * batter_first_home_run). Each player has their own line, so the line
 * lives at the outcome level — `marketLabel` can't carry it.
 *
 * Add to this list when a new prop prefix appears (e.g. `goalie_`,
 * `quarterback_`); `formatOutcomeLabel` and `marketLabel` both consult it.
 */
const PLAYER_PROP_PREFIXES: readonly string[] = [
  "player_",
  "batter_",
  "pitcher_",
];

function isPlayerPropMarket(marketKind: string): boolean {
  return PLAYER_PROP_PREFIXES.some(p => marketKind.startsWith(p));
}

/**
 * Format an outcome label for any market shape, gluing together the
 * `outcome_name` (e.g., team name, "Over"/"Under", "Player Name Over") and
 * the row-level `point` (e.g., -4.5, 215.5, 29.5) so the user always sees
 * exactly what line they're betting on.
 *
 *   spreads      → "Boston Celtics +4.5"  (signed)
 *   player props → "Victor Wembanyama Over 29.5"  (per-player line, never
 *                  in marketLabel since each player has their own number)
 *   team_totals  → "Atlanta Hawks Over 110.5"  (team-specific line, also
 *                   not in marketLabel because each team has their own)
 *   alternate_*  → underlying base treatment (alts already have point in
 *                   the marketLabel ladder, but per-row clarity helps)
 *   else         → just `outcome_name`  (point either lives in marketLabel
 *                  or doesn't apply to the bet shape)
 */
export function formatOutcomeLabel(
  outcomeName: string,
  marketKind: string,
  point: number | null | undefined,
): string {
  if (point == null) return outcomeName;
  // Player props (player_*, batter_*, pitcher_*): point is per-outcome
  // (each player has their own line) and marketLabel doesn't include it,
  // so the side label MUST.
  if (isPlayerPropMarket(marketKind)) {
    return `${outcomeName} ${point}`;
  }
  const { family } = parseMarketKind(marketKind);
  // Spreads: signed point bound to the outcome's team.
  if (family === "spreads") {
    const sign = point > 0 ? "+" : "";
    return `${outcomeName} ${sign}${point}`;
  }
  // Team totals: per-team line, marketLabel can't carry both teams' lines.
  if (family === "team_totals") {
    return `${outcomeName} ${point}`;
  }
  // Game totals / h2h / unknown: marketLabel already carries the line
  // (or the bet shape has no line) — return outcome unchanged.
  return outcomeName;
}

/** Side-column label for single-leg modes (EV, FB offered leg).
 * Composes via `formatOutcomeLabel` so all market shapes get consistent
 * line treatment — spreads sign-prefixed, player props point-suffixed. */
export function sideLabel(op: EdgeOpportunity): string {
  if (op.mode === "ev") {
    return formatOutcomeLabel(op.raw.outcome_name, op.market_kind, op.point);
  }
  if (op.mode === "free_bet") {
    return formatOutcomeLabel(
      op.raw.free_leg.outcome_name, op.market_kind, op.raw.free_leg.point,
    );
  }
  if (op.mode === "profit_boost") {
    return formatOutcomeLabel(
      op.raw.boost_leg.outcome_name, op.market_kind, op.raw.boost_leg.point,
    );
  }
  const first = op.legs[0];
  if (!first) return "";
  return formatOutcomeLabel(first.outcome_name, op.market_kind, first.point);
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
  // arb / ev — both positive-is-good %. Negative EV (fade candidates)
  // gets a red tint so the sign is visually obvious in dense tables.
  const pct = op.edge_pct;
  if (pct >= 5) return "text-price-up";
  if (pct >= 2) return "text-accent";
  if (pct >= 1) return "text-flash";
  if (pct < 0) return "text-price-down";
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
