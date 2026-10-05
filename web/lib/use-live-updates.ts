"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";
import type { ScopedMutator } from "swr";
import {
  LIVE_UPDATE_EVENT_TYPES,
  prefixesForLiveEvent,
} from "./live-update-prefixes";

/**
 * Subscribe to the backend's SSE event stream (`/api/stream/odds`) and
 * trigger SCOPED SWR revalidations on every event.
 *
 * Why scoping matters: a naive `mutate(() => true)` on every tick
 * revalidates EVERY cached SWR key. With ~25 hooks mounted across a
 * page, one tick fans out to dozens of concurrent HTTP fetches — that
 * saturates the main thread and starves modals/other UI of microtask
 * time (we hit this; symptom was the account-pool modal hanging on
 * "Loading…"). The backend tags each event with a `type` field, so we
 * can map type → SWR key prefix(es) and only revalidate the keys that
 * could plausibly have changed.
 *
 * The backend coalesces upserts into at most one tick per 1.0s, so even
 * the dumb-tick path can't flood the UI.
 *
 * Mount this hook ONCE at the app root (inside `SwrProvider`). Every
 * SWR-backed page automatically gets push-driven freshness — no per-page
 * wiring required.
 *
 * Event handling:
 *   - `connected` (fired on subscribe + after reconnect): full
 *     revalidate so the UI catches up on anything that changed during
 *     the disconnect gap. EventSource auto-reconnects on TCP drop.
 *   - `tick`      : scanner endpoints only (see TYPE_TO_PREFIXES).
 *   - `heartbeat` : ignored (idle keepalive only).
 *   - unknown     : full revalidate, so new event types added on the
 *                   backend don't silently fail to surface in the UI.
 */

/**
 * Map each SSE event `type` to the SWR-key prefixes it should
 * invalidate. Keys are matched by `String.startsWith` — covers both
 * bare-path keys (`/api/ev`) and querystring variants (`/api/ev?...`).
 *
 * Keep this in sync with `server/odds/events.py` (mark_dirty / publish
 * call sites).
 */
/**
 * Invalidate SWR keys matching any of the given prefixes. We only ever
 * use string keys in this app, so non-string keys (arrays, objects) are
 * left alone.
 */
function revalidateByPrefixes(
  mutate: ScopedMutator,
  prefixes: readonly string[],
): void {
  mutate(
    (key) =>
      typeof key === "string" && prefixes.some((p) => key.startsWith(p)),
  );
}

/**
 * Full-cache revalidation — used for `connected` (reconnect catch-up)
 * and for unknown event types (forward-compatibility: a new backend
 * event type still triggers freshness instead of silently dropping).
 */
function revalidateAll(mutate: ScopedMutator): void {
  mutate(() => true);
}

export function useLiveUpdates(): void {
  const { mutate } = useSWRConfig();
  // Stash mutate in a ref so the effect doesn't re-subscribe just
  // because SWR's mutate identity changed across renders.
  const mutateRef = useRef(mutate);
  mutateRef.current = mutate;

  useEffect(() => {
    // Same env var the rest of the app uses (see web/lib/api.ts). In dev
    // this is http://127.0.0.1:8000; in prod where /api/* is proxied
    // through Next, it falls back to a relative URL.
    const apiBase =
      process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
    const url = `${apiBase}/api/stream/odds`;

    let es: EventSource | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const handleScopedEvent = (type: string) => {
      const prefixes = prefixesForLiveEvent(type);
      if (prefixes === null) {
        // Unknown event type — fall back to full revalidate so new
        // backend events surface without a frontend deploy.
        revalidateAll(mutateRef.current);
      } else if (prefixes.length > 0) {
        revalidateByPrefixes(mutateRef.current, prefixes);
      }
    };

    const connect = () => {
      if (closed) return;
      // Tear down any prior connection before opening a new one. The browser
      // can fire `onerror` repeatedly and our manual reconnect could otherwise
      // leave the old EventSource (with its listeners) dangling — a slow leak
      // of connections + handlers across the tab's lifetime.
      es?.close();
      es = new EventSource(url);

      // Initial connect OR reconnect — both invalidate everything.
      // Browser EventSource auto-reconnects on drop and re-fires the
      // `connected` event when the server's handler restarts.
      es.addEventListener("connected", () => {
        revalidateAll(mutateRef.current);
      });

      // Typed event handlers — each only invalidates the keys that
      // could plausibly be stale. See TYPE_TO_PREFIXES above.
      for (const type of LIVE_UPDATE_EVENT_TYPES) {
        es.addEventListener(type, () => handleScopedEvent(type));
      }

      // `heartbeat` is intentionally ignored. The browser keeps the
      // connection alive on its end; the heartbeat just satisfies any
      // proxy / NAT idle timeout in between.

      es.onerror = () => {
        // EventSource auto-reconnects on most transient errors. If the
        // server is genuinely gone, we want to fail loudly in the
        // console for debugging but NOT crash the app.
        if (es?.readyState === EventSource.CLOSED) {
          // Browser gave up — manual reconnect after a short delay. Guard
          // against stacking multiple pending reconnects if onerror fires
          // repeatedly before the timer elapses.
          if (!closed && reconnectTimer === null) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = null;
              connect();
            }, 2_000);
          }
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      es?.close();
    };
  }, []); // intentionally no deps — subscription is process-lifetime
}
