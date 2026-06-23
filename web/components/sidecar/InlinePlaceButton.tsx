"use client";
import { useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Check, Loader2, Zap, AlertTriangle } from "lucide-react";

import { BASE, fetchJson } from "@/lib/api";

/**
 * InlinePlaceButton — one-click POST /api/sidecar/place for the account-
 * first /sidecar flow. No modal. The button fires immediately, then
 * shows inline status (spinner → ticket # or error → reset after 8s).
 *
 * The pinned `customerId` flows into the request body so the splitter
 * constrains the plan to that one account and stacks multi-parlays on
 * it. The Kelly fraction comes from /api/sidecar/settings (Half by
 * default, persisted via /settings).
 */
export interface InlinePlaceButtonProps {
  evRowId: string;
  fullKellyPct: number;
  customerId: string;
  /** Account's max_parlay_stake — used purely for the disabled-state
      label when the row's Kelly stake is below the $30 floor (which can
      happen only when the floor would apply). */
  accountCap: number;
  /** Account's available balance — used to disable the button when
      there's no headroom. */
  availableBalance: number;
  /** Account's display label, surfaced in the hover title. */
  accountLabel: string;
}

interface SidecarSettings {
  bankroll: number;
  default_kelly: "full" | "half" | "quarter";
}

const STAKE_FLOOR = 30;

function kellyMultiplier(f: "full" | "half" | "quarter"): number {
  return f === "full" ? 1 : f === "half" ? 0.5 : 0.25;
}

function roundTo5(n: number): number {
  return Math.round(n / 5) * 5;
}

function computeStake(
  fraction: "full" | "half" | "quarter",
  fullKellyPct: number,
  bankroll: number,
): number {
  return roundTo5((fullKellyPct / 100) * kellyMultiplier(fraction) * bankroll);
}

type FireStatus =
  | { kind: "idle" }
  | { kind: "firing" }
  | { kind: "ok"; jobId: string; assignments: number }
  | { kind: "err"; msg: string };

export function InlinePlaceButton(props: InlinePlaceButtonProps) {
  const { data: settings } = useSWR<SidecarSettings>(
    "/api/sidecar/settings",
    fetchJson,
    { refreshInterval: 60_000 },
  );
  const [status, setStatus] = useState<FireStatus>({ kind: "idle" });

  const kellyTarget = settings
    ? computeStake(
        settings.default_kelly,
        props.fullKellyPct,
        settings.bankroll,
      )
    : null;

  // Effective stake = clamped to account headroom + cap. If above cap, the
  // splitter multi-fires; we still surface the Kelly target in the label
  // so the user knows what'll be attempted.
  const effectiveBudget = Math.min(
    kellyTarget ?? 0,
    Math.floor(props.availableBalance / 5) * 5,
  );
  const belowFloor = effectiveBudget < STAKE_FLOOR;

  async function fire() {
    if (!settings || status.kind === "firing") return;
    setStatus({ kind: "firing" });
    try {
      const res = await fetch(`${BASE}/api/sidecar/place`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ev_row_id: props.evRowId,
          kelly_fraction: settings.default_kelly,
          customer_id: props.customerId,
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body.slice(0, 200)}`);
      }
      const payload = (await res.json()) as {
        job_id: string;
        plan_preview?: {
          status?: string;
          assignments?: { customer_id: string; amount: number }[];
        } | null;
      };
      const assignmentCount =
        payload.plan_preview?.assignments?.length ?? 0;
      setStatus({
        kind: "ok",
        jobId: payload.job_id,
        assignments: assignmentCount,
      });
      // Reset after 8s so the row can fire again if a fresh signal lands.
      setTimeout(() => setStatus({ kind: "idle" }), 8000);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setStatus({ kind: "err", msg });
      setTimeout(() => setStatus({ kind: "idle" }), 8000);
    }
  }

  // --- Render branches ---

  if (status.kind === "firing") {
    return (
      <span
        className={clsx(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm",
          "text-[10px] font-semibold tracking-wider uppercase",
          "text-text-2 bg-bg-2",
        )}
      >
        <Loader2 size={10} className="animate-spin" aria-hidden />
        Firing…
      </span>
    );
  }

  if (status.kind === "ok") {
    return (
      <span
        className={clsx(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm",
          "text-[10px] font-semibold tracking-wider uppercase",
          "text-price-up bg-price-up/15",
        )}
        title={`job_id: ${status.jobId}`}
      >
        <Check size={10} aria-hidden />
        Sent ({status.assignments}×)
      </span>
    );
  }

  if (status.kind === "err") {
    return (
      <span
        className={clsx(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm",
          "text-[10px] font-semibold tracking-wider uppercase",
          "text-price-down bg-price-down/15",
        )}
        title={status.msg}
      >
        <AlertTriangle size={10} aria-hidden />
        Failed
      </span>
    );
  }

  // idle
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        fire();
      }}
      disabled={belowFloor || !settings}
      className={clsx(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm",
        "text-[10px] font-semibold tracking-wider uppercase",
        "transition-colors",
        "focus-visible:outline focus-visible:outline-1 focus-visible:outline-violet-accent",
        belowFloor || !settings
          ? "text-text-3 bg-bg-2 cursor-not-allowed"
          : "text-violet-accent bg-violet-accent/15 hover:bg-violet-accent/25 hover:text-text-1",
      )}
      title={
        belowFloor
          ? `Stake $${effectiveBudget} below $30 floor on ${props.accountLabel}`
          : `Fire on ${props.accountLabel} (cap $${props.accountCap})`
      }
    >
      <Zap size={10} aria-hidden />
      {kellyTarget === null
        ? "Place"
        : `Place $${kellyTarget.toLocaleString()}`}
    </button>
  );
}
