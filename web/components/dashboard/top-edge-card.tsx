"use client";
import Link from "next/link";
import clsx from "clsx";
import {
  ArrowRight,
  Scale,
  Sparkles,
  TrendingUp,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { BookLogo } from "@/components/book-logo";
import { EmptyState } from "@/components/empty-state";
import { SPORTS, type SportKey } from "@/lib/sports";

/**
 * Compact "top opportunity right now" card — used for both Top Arb and Top
 * +EV on the dashboard. One row of data, plus a clickable header link out
 * to the edges workbench filtered to that mode.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────┐
 *   │ icon  MODE · title           open in edges → │
 *   │ 1.42%  chip  event_short  BOOK_A / BOOK_B    │
 *   └──────────────────────────────────────────────┘
 *
 * If no opportunity is available, renders an EmptyState with a Refresh
 * action the parent wires up.
 */

type Mode = "arb" | "ev";

interface TopEdgeData {
  sport_key: string;
  home_team: string;
  away_team: string;
  headline_pct: number;        // roi_pct for arb, ev_pct for ev
  market_label: string;
  books: [string, string?];    // [bookA] for ev, [bookA, bookB] for arb
}

const MODE_UI: Record<
  Mode,
  {
    title: string;
    icon: LucideIcon;
    accent: string;
    chipClass: string;
    pctClass: string;
    href: string;
    emptyTitle: string;
    emptyBody: string;
    // Distinct from `icon` (header accent): `emptyIcon` is the semantic glyph
    // shown inside <EmptyState> — Scale for arb's two-sided balance,
    // TrendingUp for +EV's directional signal.
    emptyIcon: LucideIcon;
  }
> = {
  arb: {
    title: "Top arb right now",
    icon: Zap,
    accent: "price-up",
    chipClass: "bg-price-up/15 text-price-up border-price-up/40",
    pctClass: "text-price-up",
    href: "/edges?modes=arb",
    emptyTitle: "No arbitrage right now",
    emptyBody:
      "The scanner is running, but cross-book prices don't yield a two-way lock. Try refreshing or widening your visible-books set.",
    emptyIcon: Scale,
  },
  ev: {
    title: "Top +EV right now",
    icon: Sparkles,
    accent: "violet-accent",
    chipClass: "bg-violet-accent/15 text-violet-accent border-violet-accent/40",
    pctClass: "text-violet-accent",
    href: "/edges?modes=ev",
    emptyTitle: "No +EV right now",
    emptyBody:
      "No offered price is beating the sharp consensus by your EV threshold. Add Pinnacle/Circa to your Visible Books or wait for the next fetch cycle.",
    emptyIcon: TrendingUp,
  },
};

export function TopEdgeCard({
  mode,
  data,
  onRefresh,
  isValidating,
}: {
  mode: Mode;
  data: TopEdgeData | null;
  onRefresh: () => void;
  isValidating: boolean;
}) {
  const ui = MODE_UI[mode];
  const Icon = ui.icon;
  const EmptyIcon = ui.emptyIcon;

  return (
    <div className="group relative rounded-md border border-border-subtle bg-bg-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-subtle">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-2">
          <Icon size={13} className="text-text-3" aria-hidden />
          {ui.title}
        </div>
        <Link
          href={ui.href}
          className="inline-flex items-center gap-1 text-[11px] text-text-3 hover:text-accent transition-colors"
        >
          Edges
          <ArrowRight size={11} aria-hidden />
        </Link>
      </div>

      {data ? (
        <Link
          href={ui.href}
          className="flex-1 px-4 py-3 flex items-center gap-3 hover:bg-bg-2/60 transition-colors"
        >
          <span className={clsx("tabular text-[22px] font-semibold leading-none", ui.pctClass)}>
            {data.headline_pct >= 0 ? "+" : ""}
            {data.headline_pct.toFixed(2)}%
          </span>
          <span
            className={clsx(
              "text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border",
              ui.chipClass,
            )}
          >
            {mode === "arb" ? "ARB" : "EV"}
          </span>
          <div className="flex flex-col min-w-0 flex-1">
            <span className="text-[12px] text-text-1 truncate leading-tight">
              {data.away_team} @ {data.home_team}
            </span>
            <span className="text-[10px] text-text-3 truncate tabular">
              {sportLabel(data.sport_key)} · {data.market_label}
            </span>
          </div>
          <BookRow books={data.books} />
          <ArrowRight
            size={14}
            className="text-text-3 opacity-60 group-hover:text-accent group-hover:opacity-100 transition-all flex-shrink-0"
            aria-hidden
          />
        </Link>
      ) : (
        <div className="p-4 flex-1">
          <EmptyState
            icon={<EmptyIcon size={28} />}
            title={ui.emptyTitle}
            body={ui.emptyBody}
            action={{
              label: isValidating ? "Refreshing…" : "Refresh",
              onClick: onRefresh,
              variant: "primary",
            }}
          />
        </div>
      )}
    </div>
  );
}

function BookRow({ books }: { books: [string, string?] }): ReactNode {
  return (
    <div className="flex items-center gap-1 flex-shrink-0">
      <BookLogo bookKey={books[0]} mode="label" />
      {books[1] && (
        <>
          <span className="text-text-3 text-[10px]">/</span>
          <BookLogo bookKey={books[1]} mode="label" />
        </>
      )}
    </div>
  );
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

export type { TopEdgeData };
