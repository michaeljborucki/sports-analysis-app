"use client";
import { useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Zap } from "lucide-react";

import { fetchJson } from "@/lib/api";
import { ConfirmModal } from "./ConfirmModal";
import { kellyStake, type SidecarSettingsResponse } from "./SignalFeed";

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

  // Pull the sidecar bankroll + default Kelly so the button label can show
  // the dollar stake the modal will default to. Hits the SWR cache when
  // the SignalFeed has already fetched this same key — no extra round-trip.
  const { data: settings } = useSWR<SidecarSettingsResponse>(
    "/api/sidecar/settings",
    fetchJson,
    { refreshInterval: 60_000 },
  );
  const stake = settings
    ? kellyStake(settings.default_kelly, props.fullKellyPct, settings.bankroll)
    : null;

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
        {stake !== null
          ? `Auto-place $${stake.toLocaleString()}`
          : "Auto-place"}
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
