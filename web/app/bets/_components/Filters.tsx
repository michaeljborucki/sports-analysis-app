"use client";

export interface BetFilters {
  book: string;
  sport: string;
  status: string;
}

export function Filters({
  value,
  onChange,
}: {
  value: BetFilters;
  onChange: (next: BetFilters) => void;
}) {
  const sel =
    "rounded border border-border-subtle bg-bg-1 text-sm px-2 py-1";
  return (
    <div className="flex flex-wrap gap-2 items-center">
      <select
        className={sel}
        value={value.book}
        onChange={(e) => onChange({ ...value, book: e.target.value })}
      >
        <option value="">All books</option>
        <option value="coral33">Coral33</option>
        <option value="kalshi">Kalshi</option>
        <option value="polymarket">Polymarket</option>
        <option value="imported">Imported</option>
      </select>
      <select
        className={sel}
        value={value.sport}
        onChange={(e) => onChange({ ...value, sport: e.target.value })}
      >
        <option value="">All sports</option>
        <option value="mlb">MLB</option>
        <option value="nba">NBA</option>
        <option value="nfl">NFL</option>
        <option value="nhl">NHL</option>
        <option value="tennis">Tennis</option>
        <option value="soccer">Soccer</option>
        <option value="ufc">UFC</option>
      </select>
      <select
        className={sel}
        value={value.status}
        onChange={(e) => onChange({ ...value, status: e.target.value })}
      >
        <option value="">All statuses</option>
        <option value="open">Open</option>
        <option value="win">Win</option>
        <option value="loss">Loss</option>
        <option value="push">Push</option>
        <option value="pending">Pending</option>
      </select>
    </div>
  );
}
