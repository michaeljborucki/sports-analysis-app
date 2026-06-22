"use client";
import { useState } from "react";
import clsx from "clsx";
import { Zap } from "lucide-react";

import { ConfirmModal } from "./ConfirmModal";

export interface AutoPlaceButtonProps {
  evRowId: string;
  sportKey: string;
  marketLabel: string;
  sideLabel: string;
  offeredPriceAmerican: number;
  evPct: number;
  fullKellyPct: number;
  /** Optional className extension for layout containers. */
  className?: string;
}

/**
 * Compact "Auto-place" pill rendered inline on the /edges row when the
 * row is a Coral33 +EV opportunity flagged parlay-eligible
 * (`wager_type ∈ {parlay, both}`). Clicking opens the ConfirmModal.
 *
 * Visual: matches the existing chip vocabulary (`text-violet-accent` ring
 * + uppercase tracking-wider label) so it reads as a primary action without
 * overpowering the row's edge/price columns.
 *
 * Eligibility is enforced by the *caller* (the /edges row component) — this
 * button is a dumb portal-opener and assumes the parent has already
 * filtered. Keeping the predicate at the caller avoids leaking row-shape
 * knowledge into the sidecar package.
 */
export function AutoPlaceButton(props: AutoPlaceButtonProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          // Don't bubble into row click / expand handlers.
          e.stopPropagation();
          setOpen(true);
        }}
        className={clsx(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm",
          "text-[10px] font-semibold tracking-wider uppercase",
          "text-violet-accent bg-violet-accent/15",
          "hover:bg-violet-accent/25 hover:text-text-1 transition-colors",
          "focus-visible:outline focus-visible:outline-1 focus-visible:outline-violet-accent",
          props.className,
        )}
        title="Auto-place this +EV parlay via the sidecar"
      >
        <Zap size={10} aria-hidden />
        Auto-place
      </button>
      {open && (
        <ConfirmModal
          evRowId={props.evRowId}
          sportKey={props.sportKey}
          marketLabel={props.marketLabel}
          sideLabel={props.sideLabel}
          offeredPriceAmerican={props.offeredPriceAmerican}
          evPct={props.evPct}
          fullKellyPct={props.fullKellyPct}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
