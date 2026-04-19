export function formatAmerican(odds: number): string {
  if (odds === 0) return "-";
  return odds > 0 ? `+${odds}` : `${odds}`;
}

export function formatUnits(u: number): string {
  return `${u.toFixed(u % 1 === 0 ? 0 : 1)}u`;
}

export function formatPct(p: number, signed = false): string {
  const s = `${p.toFixed(1)}%`;
  return signed && p > 0 ? `+${s}` : s;
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export function formatBookAbbrev(key: string): string {
  const map: Record<string, string> = {
    draftkings: "DK",
    fanduel: "FD",
    betmgm: "MGM",
    betmgm_sportsbook: "MGM",
    caesars: "CZR",
    williamhill_us: "CZR",
    fanatics: "FAN",
    hardrockbet: "HRB",
    espnbet: "ESPN",
    pointsbetus: "PB",
    betrivers: "BR",
    unibet_us: "UNI",
    twinspires: "TS",
    wynnbet: "WYN",
    superbook: "SB",
    lowvig: "LV",
    betonlineag: "BOL",
    bovada: "BVD",
    betus: "BU",
    mybookieag: "MBK",
  };
  return map[key] ?? key.slice(0, 3).toUpperCase();
}
