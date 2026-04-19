/**
 * Registry of sportsbook metadata — brand colors, labels, region, display priority.
 * Color pairs chosen to read as "badge / chip" in dense tables. Not pixel-perfect
 * brand — uniform pill styling wins over mismatched real logos in a 15-book row.
 */

export type Region = "US" | "EU" | "UK" | "ROW";

export interface BookInfo {
  key: string;
  name: string;
  label: string;       // 2–4 chars shown on the pill
  bg: string;          // pill background
  fg: string;          // pill text color
  region: Region;
  priority: number;    // lower = shown first; defaults shown first
}

const BOOK_LIST: BookInfo[] = [
  // Top US books
  { key: "draftkings",   name: "DraftKings",   label: "DK",   bg: "#000000", fg: "#53D337", region: "US", priority: 1 },
  { key: "fanduel",      name: "FanDuel",      label: "FD",   bg: "#1493FF", fg: "#FFFFFF", region: "US", priority: 2 },
  { key: "betmgm",       name: "BetMGM",       label: "MGM",  bg: "#000000", fg: "#B8975A", region: "US", priority: 3 },
  { key: "caesars",      name: "Caesars",      label: "CZR",  bg: "#002554", fg: "#D4AF37", region: "US", priority: 4 },
  { key: "williamhill_us", name: "Caesars (WH US)", label: "CZR", bg: "#002554", fg: "#D4AF37", region: "US", priority: 5 },
  { key: "fanatics",     name: "Fanatics",     label: "FAN",  bg: "#181818", fg: "#B30B24", region: "US", priority: 6 },
  { key: "hardrockbet",  name: "Hard Rock",    label: "HRB",  bg: "#000000", fg: "#E7232C", region: "US", priority: 7 },
  { key: "hardrockbet_oh", name: "Hard Rock OH", label: "HRO", bg: "#000000", fg: "#E7232C", region: "US", priority: 8 },
  { key: "espnbet",      name: "ESPN BET",     label: "ESPN", bg: "#000000", fg: "#D50A0A", region: "US", priority: 9 },
  { key: "pointsbetus",  name: "PointsBet",    label: "PB",   bg: "#E40521", fg: "#FFFFFF", region: "US", priority: 10 },
  { key: "betrivers",    name: "BetRivers",    label: "BR",   bg: "#1E3A8A", fg: "#F7941D", region: "US", priority: 11 },
  { key: "fliff",        name: "Fliff",        label: "FLI",  bg: "#00B050", fg: "#FFFFFF", region: "US", priority: 12 },
  { key: "rebet",        name: "Rebet",        label: "REB",  bg: "#3B82F6", fg: "#FFFFFF", region: "US", priority: 13 },
  { key: "ballybet",     name: "Bally Bet",    label: "BAL",  bg: "#C9A227", fg: "#000000", region: "US", priority: 14 },
  { key: "betparx",      name: "betPARX",      label: "PRX",  bg: "#6D28D9", fg: "#FFFFFF", region: "US", priority: 15 },

  // US offshore / gray
  { key: "bovada",       name: "Bovada",       label: "BVD",  bg: "#E63946", fg: "#FFFFFF", region: "US", priority: 30 },
  { key: "betonlineag",  name: "BetOnline",    label: "BOL",  bg: "#1E293B", fg: "#F5A524", region: "US", priority: 31 },
  { key: "betus",        name: "BetUS",        label: "BU",   bg: "#0F172A", fg: "#2CB459", region: "US", priority: 32 },
  { key: "mybookieag",   name: "MyBookie",     label: "MBK",  bg: "#FACC15", fg: "#000000", region: "US", priority: 33 },
  { key: "lowvig",       name: "LowVig",       label: "LV",   bg: "#111827", fg: "#F5A524", region: "US", priority: 34 },
  { key: "betanysports", name: "BetAnySports", label: "BAS",  bg: "#0EA5E9", fg: "#FFFFFF", region: "US", priority: 35 },

  // Pinnacle (sharp, EU)
  { key: "pinnacle",     name: "Pinnacle",     label: "PIN",  bg: "#0A1F44", fg: "#FBBF24", region: "EU", priority: 20 },

  // Top UK
  { key: "williamhill",  name: "William Hill", label: "WH",   bg: "#002664", fg: "#FFDE00", region: "UK", priority: 50 },
  { key: "bet365",       name: "bet365",       label: "B365", bg: "#027B5B", fg: "#FFE500", region: "UK", priority: 51 },
  { key: "betfair_ex_uk", name: "Betfair Ex UK", label: "BFX",bg: "#FFDE00", fg: "#000000", region: "UK", priority: 52 },
  { key: "paddypower",   name: "Paddy Power",  label: "PPW",  bg: "#00843D", fg: "#FFFFFF", region: "UK", priority: 53 },
  { key: "ladbrokes_uk", name: "Ladbrokes",    label: "LAD",  bg: "#DA291C", fg: "#FFFFFF", region: "UK", priority: 54 },
  { key: "coral",        name: "Coral",        label: "COR",  bg: "#BE1622", fg: "#FFFFFF", region: "UK", priority: 55 },
  { key: "boylesports",  name: "BoyleSports",  label: "BOY",  bg: "#0E4C92", fg: "#FDE047", region: "UK", priority: 56 },
  { key: "betway",       name: "Betway",       label: "BTW",  bg: "#000000", fg: "#00A826", region: "UK", priority: 57 },
  { key: "betvictor",    name: "BetVictor",    label: "BVC",  bg: "#D50000", fg: "#FFDE00", region: "UK", priority: 58 },
  { key: "virginbet",    name: "Virgin Bet",   label: "VIR",  bg: "#D71920", fg: "#FFFFFF", region: "UK", priority: 59 },
  { key: "livescorebet", name: "LiveScore Bet", label: "LSB", bg: "#005FA1", fg: "#F59E0B", region: "UK", priority: 60 },
  { key: "grosvenor",    name: "Grosvenor",    label: "GRO",  bg: "#1E40AF", fg: "#D4AF37", region: "UK", priority: 61 },
  { key: "smarkets",     name: "Smarkets",     label: "SMK",  bg: "#0F172A", fg: "#10B981", region: "UK", priority: 62 },
  { key: "matchbook",    name: "Matchbook",    label: "MBK",  bg: "#0EA5E9", fg: "#FFFFFF", region: "UK", priority: 63 },
  { key: "sport888",     name: "888sport",     label: "888",  bg: "#F59E0B", fg: "#000000", region: "UK", priority: 64 },
  { key: "marathonbet",  name: "Marathonbet",  label: "MAR",  bg: "#EF4444", fg: "#FFFFFF", region: "UK", priority: 65 },

  // EU
  { key: "betfair_ex_eu", name: "Betfair Ex EU", label: "BFX", bg: "#FFDE00", fg: "#000000", region: "EU", priority: 70 },
  { key: "unibet_fr",    name: "Unibet FR",    label: "UNF",  bg: "#147A3D", fg: "#FDE047", region: "EU", priority: 71 },
  { key: "unibet_nl",    name: "Unibet NL",    label: "UNN",  bg: "#147A3D", fg: "#FDE047", region: "EU", priority: 72 },
  { key: "unibet_se",    name: "Unibet SE",    label: "UNS",  bg: "#147A3D", fg: "#FDE047", region: "EU", priority: 73 },
  { key: "leovegas",     name: "LeoVegas",     label: "LEO",  bg: "#FF6600", fg: "#FFFFFF", region: "EU", priority: 74 },
  { key: "leovegas_se",  name: "LeoVegas SE",  label: "LES",  bg: "#FF6600", fg: "#FFFFFF", region: "EU", priority: 75 },
  { key: "tipico_de",    name: "Tipico DE",    label: "TIP",  bg: "#DA291C", fg: "#FFFFFF", region: "EU", priority: 76 },
  { key: "winamax_de",   name: "Winamax DE",   label: "WDE",  bg: "#1E40AF", fg: "#F97316", region: "EU", priority: 77 },
  { key: "winamax_fr",   name: "Winamax FR",   label: "WFR",  bg: "#1E40AF", fg: "#F97316", region: "EU", priority: 78 },
  { key: "pmu_fr",       name: "PMU",          label: "PMU",  bg: "#6B21A8", fg: "#FDE047", region: "EU", priority: 79 },
  { key: "casumo",       name: "Casumo",       label: "CAS",  bg: "#EC4899", fg: "#FFFFFF", region: "EU", priority: 80 },
  { key: "betsson",      name: "Betsson",      label: "BSS",  bg: "#10B981", fg: "#FDE047", region: "EU", priority: 81 },
  { key: "nordicbet",    name: "NordicBet",    label: "NOR",  bg: "#1E3A8A", fg: "#EF4444", region: "EU", priority: 82 },
  { key: "coolbet",      name: "Coolbet",      label: "COL",  bg: "#0EA5E9", fg: "#FFFFFF", region: "EU", priority: 83 },
  { key: "everygame",    name: "Everygame",    label: "EVG",  bg: "#1E3A8A", fg: "#D4AF37", region: "EU", priority: 84 },
  { key: "onexbet",      name: "1xBet",        label: "1X",   bg: "#1E40AF", fg: "#F97316", region: "EU", priority: 85 },
];

export const BOOKS: Record<string, BookInfo> = Object.fromEntries(
  BOOK_LIST.map(b => [b.key, b])
);

export const BOOK_ORDER: string[] = [...BOOK_LIST]
  .sort((a, b) => a.priority - b.priority)
  .map(b => b.key);

/** Default books shown on first load — top ~10 US books a sharp would care about. */
export const DEFAULT_VISIBLE_BOOKS: string[] = [
  "draftkings",
  "fanduel",
  "betmgm",
  "caesars",
  "fanatics",
  "hardrockbet",
  "espnbet",
  "betrivers",
  "pinnacle",
  "bovada",
];

export function bookInfo(key: string): BookInfo {
  return (
    BOOKS[key] ?? {
      key,
      name: key,
      label: key.slice(0, 3).toUpperCase(),
      bg: "#1C2530",
      fg: "#9AA5B4",
      region: "ROW" as Region,
      priority: 999,
    }
  );
}
