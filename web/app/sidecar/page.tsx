"use client";
import { FreshnessChip } from "@/components/freshness-chip";

import { AccountPoolGrid } from "@/components/sidecar/AccountPoolGrid";
import { SignalFeed } from "@/components/sidecar/SignalFeed";
import { RunLog } from "@/components/sidecar/RunLog";
import { ModeToggle } from "@/components/sidecar/ModeToggle";
import { ActiveSignalsPanel } from "@/components/sidecar/ActiveSignalsPanel";

/**
 * /sidecar — the auto-bet sidecar dashboard.
 *
 * Layout (Bloomberg-terminal style, three-column workspace):
 *   ┌────────────── header (title + ModeToggle + FreshnessChip) ──────────────┐
 *   │                                                                          │
 *   │  ┌────────────────┐  ┌────────────────────┐  ┌──────────────────────┐  │
 *   │  │   SignalFeed   │  │ ActiveSignalsPanel │  │   AccountPoolGrid    │  │
 *   │  │   (left, lg)   │  │  (center, target)  │  │   (right, 7 cards)   │  │
 *   │  │                │  │                    │  │                      │  │
 *   │  └────────────────┘  └────────────────────┘  └──────────────────────┘  │
 *   │                                                                          │
 *   │  ┌──────────────────────────── RunLog ────────────────────────────────┐ │
 *   │  └────────────────────────────────────────────────────────────────────┘ │
 *   └──────────────────────────────────────────────────────────────────────────┘
 *
 * The page composes the five H1-H5 components — no business logic lives
 * here. Each component owns its own SWR fetch and refresh cadence; cache
 * mode + visible-books prefs flow through the usual SwrProvider context.
 */
export default function SidecarPage() {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-[28px] leading-[30px] font-semibold tracking-tight text-text-1">
            Sidecar
          </h1>
          <span className="text-xs text-text-3 tabular hidden sm:inline">
            coral33 auto-place · sequential placements with jitter
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ModeToggle />
          <FreshnessChip staleAfterSeconds={300} />
        </div>
      </header>

      {/* Three-column workspace.
          - SignalFeed (left, 5/12)  — actionable +EV parlay-eligible rows
          - ActiveSignalsPanel (center, 4/12) — armed signals + delta gauge
          - AccountPoolGrid (right, 3/12) — pool drain order
          On md/sm screens the columns stack in source order. */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5 order-1">
          <SignalFeed />
        </div>
        <div className="lg:col-span-4 order-2">
          <ActiveSignalsPanel />
        </div>
        <div className="lg:col-span-3 order-3">
          <AccountPoolGrid />
        </div>
      </div>

      {/* Run log spans the full width — placements per job often expand
          to 4-5 rows each, and a wide layout reads cleanly at the dense
          /accounts row height without truncating ev_row_id. */}
      <RunLog />
    </div>
  );
}
