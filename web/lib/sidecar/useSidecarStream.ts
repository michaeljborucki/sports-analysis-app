"use client";
import { useEffect, useState } from "react";

/**
 * Typed SSE subscription helper scoped to a single sidecar job_id.
 *
 * Subscribes to the existing `/api/stream/odds` channel (the backend
 * fans out *all* event types over a single SSE connection) and filters
 * incoming `sidecar_placement` + `sidecar_partial_fill` events down to
 * the events whose payload matches the caller's `job_id`.
 *
 * Returns an append-only ordered array of events for the job. The hook
 * is null-safe — passing `null` as `jobId` no-ops (used by the confirm
 * modal before the user clicks Confirm).
 *
 * The accumulator is intentionally per-mount: the modal lifecycle owns
 * the receipt-sequence view, and re-opening the modal on a fresh
 * placement should not surface stale events from a previous job.
 *
 * Note: when the backend wires the new event types (Phase F of the
 * sidecar plan), the event names here must match `server/api/stream.py`.
 */

export interface SidecarPlacementEvent {
  type: "sidecar_placement";
  job_id: string;
  placement_id: string;
  picked_account: string | null;
  stake: number | null;
  result: string;
  ticket_number: string | null;
  error_message: string | null;
  created_at: number;
}

export interface SidecarPartialFillEvent {
  type: "sidecar_partial_fill";
  job_id: string;
  placement_id: string;
  filled: number;
  target: number;
  created_at: number;
}

export type SidecarEvent = SidecarPlacementEvent | SidecarPartialFillEvent;

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function useSidecarStream(jobId: string | null): SidecarEvent[] {
  // Bucket events by job_id so switching jobs starts a fresh accumulator
  // *without* calling setState synchronously inside the effect body
  // (which triggers a cascading-renders lint warning under React 19).
  // The consumer always reads the slice keyed by the current jobId, so
  // stale buckets from previous jobs are invisible.
  const [byJob, setByJob] = useState<Record<string, SidecarEvent[]>>({});

  useEffect(() => {
    if (!jobId) return;

    let es: EventSource | null = null;
    let closed = false;

    function handle(raw: MessageEvent, type: SidecarEvent["type"]) {
      try {
        const data = JSON.parse(raw.data);
        if (data?.job_id !== jobId) return;
        setByJob((prev) => {
          const next = { ...prev };
          const list = next[jobId!] ?? [];
          next[jobId!] = [...list, { type, ...data } as SidecarEvent];
          return next;
        });
      } catch {
        // Drop malformed payloads silently — SSE has no schema guarantee.
      }
    }

    const connect = () => {
      if (closed) return;
      es = new EventSource(`${API_BASE}/api/stream/odds`);
      es.addEventListener("sidecar_placement", (e) =>
        handle(e as MessageEvent, "sidecar_placement"),
      );
      es.addEventListener("sidecar_partial_fill", (e) =>
        handle(e as MessageEvent, "sidecar_partial_fill"),
      );
      es.onerror = () => {
        if (es?.readyState === EventSource.CLOSED && !closed) {
          setTimeout(connect, 2_000);
        }
      };
    };

    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, [jobId]);

  return jobId ? (byJob[jobId] ?? EMPTY) : EMPTY;
}

const EMPTY: SidecarEvent[] = [];
