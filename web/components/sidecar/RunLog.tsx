"use client";
import { useMemo } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { ScrollText, AlertCircle } from "lucide-react";

import { fetchJson } from "@/lib/api";

/**
 * RunLog — dense, newest-first table of sidecar placements grouped by
 * job_id. Reads /api/sidecar/runs?limit=100 (Phase F will ship the
 * endpoint; SWR will retry until then). Each job_id becomes one section
 * header with a row per placement underneath; the rows mirror what the
 * audit table (sidecar_placements) stores.
 *
 * Visual: borrows the Bloomberg-terminal table vocabulary from the
 * accounts page — uppercase column headers, tabular figures, and
 * status pills that match the existing `text-price-up/down` palette.
 */

interface RunPlacement {
  placement_id: string;
  job_id: string;
  created_at: number;
  ev_row_id: string;
  ev_leg: string;
  parlay_name: string;
  kelly_fraction: string;
  target_stake: number;
  stake: number | null;
  mode: string;
  picked_account: string | null;
  result: string;
  ticket_number: string | null;
  error_message: string | null;
  /** 'user' | 'delta_tick' — added in Phase B4. */
  trigger_source?: string | null;
}

interface RunsResponse {
  placements: RunPlacement[];
}

interface JobGroup {
  job_id: string;
  trigger_source: string;
  created_at: number;
  mode: string;
  ev_row_id: string;
  total_target: number;
  total_filled: number;
  placements: RunPlacement[];
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

function fmtTimeAgo(epoch: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function RunLog() {
  const { data, isLoading, error } = useSWR<RunsResponse>(
    "/api/sidecar/runs?limit=100",
    fetchJson,
    { refreshInterval: 10_000 },
  );

  const jobs = useMemo<JobGroup[]>(() => {
    if (!data?.placements) return [];
    const byJob = new Map<string, JobGroup>();
    for (const p of data.placements) {
      let g = byJob.get(p.job_id);
      if (!g) {
        g = {
          job_id: p.job_id,
          trigger_source: p.trigger_source || "user",
          created_at: p.created_at,
          mode: p.mode,
          ev_row_id: p.ev_row_id,
          total_target: 0,
          total_filled: 0,
          placements: [],
        };
        byJob.set(p.job_id, g);
      }
      g.placements.push(p);
      g.total_target = Math.max(g.total_target, p.target_stake);
      if (p.stake != null && (p.result === "placed" || p.result === "dry_run")) {
        g.total_filled += p.stake;
      }
      // Carry the newest row's timestamp on the group — placements within
      // a job arrive sequentially with a small jitter; the latest is the
      // best surface-level "when did the run land" answer.
      if (p.created_at > g.created_at) g.created_at = p.created_at;
    }
    return [...byJob.values()].sort((a, b) => b.created_at - a.created_at);
  }, [data]);

  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
          <ScrollText size={11} aria-hidden />
          Run log
          <span className="text-text-2 tabular">({jobs.length})</span>
        </h2>
        <span className="text-[10px] tabular text-text-3">
          last 100 placements
        </span>
      </header>

      {isLoading && !data && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          Loading run history…
        </div>
      )}
      {error && (
        <div className="text-price-down text-xs flex items-center gap-1.5 px-1 py-3">
          <AlertCircle size={12} aria-hidden />
          /api/sidecar/runs unreachable (Phase F endpoint pending?)
        </div>
      )}
      {!isLoading && !error && jobs.length === 0 && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          No placements yet.
        </div>
      )}

      {jobs.length > 0 && (
        <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-bg-1 text-text-2 sticky top-0">
                <tr>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[44px]">
                    Age
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Job
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px]">
                    Signal
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[80px]">
                    Account
                  </th>
                  <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[64px]">
                    Stake
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[100px]">
                    Result
                  </th>
                  <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wider text-[10px] w-[88px]">
                    Trigger
                  </th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((g) => (
                  <JobBlock key={g.job_id} group={g} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function JobBlock({ group }: { group: JobGroup }) {
  const placements = useMemo(
    () =>
      [...group.placements].sort((a, b) => a.created_at - b.created_at),
    [group.placements],
  );

  return (
    <>
      <tr className="border-t border-border-subtle bg-bg-1/40">
        <td className="px-2 py-1 text-text-3 tabular align-top">
          {fmtTimeAgo(group.created_at)}
        </td>
        <td className="px-2 py-1 align-top">
          <span className="text-text-2 tabular text-[10px]" title={group.job_id}>
            {group.job_id.slice(0, 8)}
          </span>
        </td>
        <td className="px-2 py-1 align-top text-text-2 text-[10px] truncate" colSpan={3}>
          <span className="truncate" title={group.ev_row_id}>
            {group.ev_row_id}
          </span>
          <span className="text-text-3 ml-2 tabular">
            target {fmtUsd(group.total_target)} · filled {fmtUsd(group.total_filled)}
          </span>
        </td>
        <td className="px-2 py-1 align-top">
          <ModeBadge mode={group.mode} />
        </td>
        <td className="px-2 py-1 align-top">
          <TriggerBadge source={group.trigger_source} />
        </td>
      </tr>
      {placements.map((p) => (
        <PlacementRow key={p.placement_id} p={p} />
      ))}
    </>
  );
}

function PlacementRow({ p }: { p: RunPlacement }) {
  return (
    <tr className="border-t border-border-subtle/50 hover:bg-bg-1/30">
      <td className="px-2 py-1 text-text-3 tabular text-[10px] align-top">
        {fmtTimeAgo(p.created_at)}
      </td>
      <td className="px-2 py-1 text-text-3 text-[10px] tabular align-top" title={p.placement_id}>
        └ {p.placement_id.slice(0, 6)}
      </td>
      <td className="px-2 py-1 align-top text-text-2 text-[10px]">
        <span className="text-text-3 uppercase tracking-wider mr-1.5">
          {p.kelly_fraction}
        </span>
        {p.ticket_number && (
          <span className="text-text-1 tabular">#{p.ticket_number}</span>
        )}
        {p.error_message && (
          <span className="text-price-down ml-1.5 truncate" title={p.error_message}>
            {p.error_message}
          </span>
        )}
      </td>
      <td className="px-2 py-1 align-top text-text-1 tabular">
        {p.picked_account ?? "—"}
      </td>
      <td className="px-2 py-1 align-top text-right tabular text-text-1">
        {fmtUsd(p.stake)}
      </td>
      <td className="px-2 py-1 align-top">
        <ResultBadge result={p.result} />
      </td>
      <td className="px-2 py-1 align-top text-text-3 text-[10px]">{/* trigger column intentionally blank on child rows */}</td>
    </tr>
  );
}

function ResultBadge({ result }: { result: string }) {
  const meta = (() => {
    switch (result) {
      case "placed":
        return { label: "placed", className: "text-price-up bg-price-up/15" };
      case "dry_run":
        return { label: "dry-run", className: "text-flash bg-flash/15" };
      case "partial_fill":
        return { label: "partial", className: "text-flash bg-flash/15" };
      case "no_eligible_account":
        return { label: "no acct", className: "text-text-3 bg-bg-2" };
      case "below_minimum":
        return { label: "below min", className: "text-text-3 bg-bg-2" };
      case "error":
        return { label: "error", className: "text-price-down bg-price-down/15" };
      default:
        return { label: result, className: "text-text-3 bg-bg-2" };
    }
  })();
  return (
    <span
      className={clsx(
        "inline-flex items-center px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wider uppercase",
        meta.className,
      )}
    >
      {meta.label}
    </span>
  );
}

function ModeBadge({ mode }: { mode: string }) {
  const meta =
    mode === "live"
      ? { label: "LIVE", className: "text-price-up bg-price-up/15" }
      : mode === "dry-run"
        ? { label: "DRY", className: "text-flash bg-flash/15" }
        : { label: mode.toUpperCase(), className: "text-text-3 bg-bg-2" };
  return (
    <span
      className={clsx(
        "inline-flex items-center px-1 py-0.5 rounded-sm text-[9px] font-semibold tracking-wider",
        meta.className,
      )}
    >
      {meta.label}
    </span>
  );
}

function TriggerBadge({ source }: { source: string }) {
  // `delta_tick` is the delta-driven re-arm path that keeps a signal
  // alive; `user` is a fresh modal-confirm. Color them differently so
  // glancing at the log surfaces who/what is firing the placements.
  const isDelta = source === "delta_tick" || source === "delta";
  const meta = isDelta
    ? { label: "DELTA", className: "text-accent bg-accent/15" }
    : { label: "USER", className: "text-violet-accent bg-violet-accent/15" };
  return (
    <span
      className={clsx(
        "inline-flex items-center px-1 py-0.5 rounded-sm text-[9px] font-semibold tracking-wider",
        meta.className,
      )}
      title={source}
    >
      {meta.label}
    </span>
  );
}
