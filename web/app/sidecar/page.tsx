"use client";
import { useState } from "react";
import { FreshnessChip } from "@/components/freshness-chip";

import {
  AccountPickerGrid,
  type SelectedAccount,
} from "@/components/sidecar/AccountPickerGrid";
import { SignalFeed } from "@/components/sidecar/SignalFeed";
import { RunLog } from "@/components/sidecar/RunLog";
import { ModeToggle } from "@/components/sidecar/ModeToggle";
import { ActiveSignalsPanel } from "@/components/sidecar/ActiveSignalsPanel";

/**
 * /sidecar — account-first auto-bet dashboard.
 *
 * Workflow:
 *   1) User picks one account from the AccountPickerGrid (top).
 *   2) The bet feed renders, each row showing a one-click PLACE button
 *      that fires immediately against the pinned account. The splitter
 *      stacks multi-parlays on that account (each at its cap) up to the
 *      Kelly target.
 *   3) Signals armed in this flow inherit `armed_customer_id`, so the
 *      autonomous delta-tick re-fires future top-ups on the same account.
 *
 * Until an account is picked, the bet feed stays hidden so the workflow
 * reads strictly top-down.
 */
export default function SidecarPage() {
  const [selected, setSelected] = useState<SelectedAccount | null>(null);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-[28px] leading-[30px] font-semibold tracking-tight text-text-1">
            Sidecar
          </h1>
          <span className="text-xs text-text-3 tabular hidden sm:inline">
            account-first · coral33 · one-click parlay
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ModeToggle />
          <FreshnessChip staleAfterSeconds={300} />
        </div>
      </header>

      {/* STEP 1: pick an account */}
      <AccountPickerGrid selected={selected} onSelect={setSelected} />

      {/* STEP 2: bets show up only after a pick */}
      {selected ? (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          <div className="lg:col-span-8 order-1">
            <SignalFeed selectedAccount={selected} />
          </div>
          <div className="lg:col-span-4 order-2">
            <ActiveSignalsPanel />
          </div>
        </div>
      ) : (
        <div className="border border-dashed border-border-subtle rounded-md bg-bg-0 px-4 py-8 text-center">
          <p className="text-text-2 text-sm">
            Pick an account above to see eligible +EV parlay signals.
          </p>
          <p className="text-text-3 text-xs mt-1">
            Each placement will fire on the selected account at its
            per-parlay cap; the splitter stacks multi-parlays if Kelly
            target exceeds the cap.
          </p>
        </div>
      )}

      <RunLog />
    </div>
  );
}
