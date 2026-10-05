"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";

import type { ArbOpportunity, EVOpportunity } from "@/lib/api";
import { SPORTS, type SportKey } from "@/lib/sports";
import { BookLogo } from "@/components/book-logo";
import { EdgeBar, Panel, Segmented } from "@/components/ui";
import { useNow } from "./use-now";

/**
 * "Best right now" — the dashboard hero. Merges data the page already
 * fetches (top arbs from /api/dashboard, +EV rows from /api/ev) into one
 * compact table. No extra requests. Each row links to /edges in its mode.
 */

type Kind = "arb" | "ev";
type Filter = "all" | Kind;

interface EdgeRow {
  id: string;
  kind: Kind;
  edge: number;
  sport: string;
  away: string;
  home: string;
  market: string;
  books: string[];
  commence: string;
}

const KIND_LABEL: Record<Kind, string> = { arb: "Arbitrage", ev: "+EV" };
const PER_KIND = 5;

export function BestNowPanel({
  arbs,
  evs,
}: {
  arbs: ArbOpportunity[];
  evs: EVOpportunity[] | undefined;
}) {
  const router = useRouter();
  const now = useNow();
  const [filter, setFilter] = useState<Filter>("all");

  const rows = useMemo(() => {
    const a = arbs.slice(0, PER_KIND).map(arbRow);
    const e = (evs ?? []).slice(0, PER_KIND).map(evRow);
    const pool = filter === "arb" ? a : filter === "ev" ? e : [...a, ...e];
    return pool.sort((x, y) => y.edge - x.edge);
  }, [arbs, evs, filter]);

  const max = rows.reduce((m, r) => Math.max(m, r.edge), 0);

  return (
    <Panel
      title="Best right now"
      actions={
        <>
          <Segmented<Filter>
            size="sm"
            ariaLabel="Edge type"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "arb", label: "Arbitrage" },
              { value: "ev", label: "+EV" },
            ]}
          />
          <Link
            href={filter === "all" ? "/edges" : `/edges?modes=${filter}`}
            className="inline-flex items-center gap-1 text-[length:var(--fs-12)] text-text-2 hover:text-text-1"
          >
            Open edges
            <ArrowRight size={12} aria-hidden />
          </Link>
        </>
      }
      bodyClassName="overflow-x-auto"
    >
      {rows.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <p className="text-[length:var(--fs-14)] font-medium text-text-1">
            {filter === "arb"
              ? "No arbitrage right now"
              : filter === "ev"
                ? "No +EV above 1% right now"
                : "No arbitrage or +EV right now"}
          </p>
          <p className="mx-auto mt-1 max-w-md text-[length:var(--fs-13)] text-text-3">
            The scanners are running against your visible books. New edges show up here on the next refresh.
          </p>
        </div>
      ) : (
        <table className="w-full min-w-[720px] border-collapse">
          <thead className="dt-head">
            <tr>
              <th className="dt-th w-[120px]">Edge</th>
              <th className="dt-th">Event</th>
              <th className="dt-th">Market</th>
              <th className="dt-th">Books</th>
              <th className="dt-th text-right">Starts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const href = `/edges?modes=${r.kind}`;
              return (
                <tr
                  key={r.id}
                  className="dt-row cursor-pointer"
                  onClick={() => router.push(href)}
                >
                  <td className="dt-td">
                    <EdgeBar value={r.edge} max={max}>
                      {r.edge.toFixed(2)}%
                    </EdgeBar>
                  </td>
                  <td className="dt-td max-w-[280px]">
                    <Link
                      href={href}
                      onClick={e => e.stopPropagation()}
                      className="block truncate text-text-1 hover:underline"
                    >
                      {r.away} <span className="text-text-3">at</span> {r.home}
                    </Link>
                    <span className="text-[length:var(--fs-11)] text-text-3">
                      {sportLabel(r.sport)}
                    </span>
                  </td>
                  <td className="dt-td">
                    <span className="block text-text-1">{r.market}</span>
                    <span className="text-[length:var(--fs-11)] text-text-3">
                      {KIND_LABEL[r.kind]}
                    </span>
                  </td>
                  <td className="dt-td">
                    <span className="inline-flex items-center gap-1">
                      {r.books.map((b, i) => (
                        <BookLogo key={`${b}-${i}`} bookKey={b} mode="label" />
                      ))}
                    </span>
                  </td>
                  <td className="dt-td text-right whitespace-nowrap">
                    {now != null ? <StartsCell iso={r.commence} now={now} /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function StartsCell({ iso, now }: { iso: string; now: number }) {
  const diffMin = Math.round((new Date(iso).getTime() - now) / 60_000);
  if (diffMin < 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[length:var(--fs-12)] font-semibold text-live">
        <span className="live-dot" aria-hidden />
        Live
      </span>
    );
  }
  if (diffMin < 60) {
    return (
      <span className="text-text-1">
        in <span className="tabular">{diffMin}m</span>
      </span>
    );
  }
  if (diffMin < 24 * 60) {
    return (
      <span className="tabular text-text-2">
        {new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
      </span>
    );
  }
  return (
    <span className="tabular text-text-2">
      {new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" })}
    </span>
  );
}

export function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

// ──────────────── adapters ────────────────

function arbRow(op: ArbOpportunity): EdgeRow {
  return {
    id: `arb-${op.event_id}-${op.market_kind}-${op.point ?? ""}-${op.sides.map(s => s.book).join("-")}`,
    kind: "arb",
    edge: op.roi_pct,
    sport: op.sport_key,
    away: op.away_team,
    home: op.home_team,
    market: arbMarketLabel(op.market_kind, op.point ?? null),
    books: op.sides.map(s => s.book),
    commence: op.commence_time,
  };
}

function evRow(op: EVOpportunity): EdgeRow {
  return {
    id: `ev-${op.event_id}-${op.market_kind}-${op.outcome_name}-${op.point ?? ""}-${op.book}`,
    kind: "ev",
    edge: op.ev_pct,
    sport: op.sport_key,
    away: op.away_team,
    home: op.home_team,
    market: evMarketLabel(op),
    books: [op.book],
    commence: op.commence_time,
  };
}

function humanize(kind: string): string {
  const s = kind.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function arbMarketLabel(kind: string, point: number | null): string {
  if (kind === "h2h") return "Moneyline";
  if (kind === "totals") return point != null ? `Total ${point}` : "Total";
  if (kind === "spreads") return point != null ? `Spread ±${Math.abs(point)}` : "Spread";
  return point != null ? `${humanize(kind)} ${point}` : humanize(kind);
}

function evMarketLabel(op: EVOpportunity): string {
  const k = op.market_kind;
  if (k === "h2h") return `${op.outcome_name} moneyline`;
  if (k === "totals") return op.point != null ? `${op.outcome_name} ${op.point}` : `${op.outcome_name} total`;
  if (k === "spreads")
    return op.point != null
      ? `${op.outcome_name} ${op.point > 0 ? "+" : ""}${op.point}`
      : `${op.outcome_name} spread`;
  const pt = op.point != null ? ` ${op.point}` : "";
  return `${op.outcome_name}${pt} (${humanize(k)})`;
}
