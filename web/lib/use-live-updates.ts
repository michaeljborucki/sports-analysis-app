"use client";

import { useEffect, useRef } from "react";
import { useSWRConfig } from "swr";

/**
 * Subscribe to the backend's SSE event stream (`/api/stream/odds`) and
 * trigger a global SWR revalidation on every `tick` event.
 *
 * The backend coalesces upserts into at most one tick per 100ms, so this
 * hook can't flood the UI even when Kalshi/Polymarket WebSocket streams
 * push hundreds of price updates per second.
 *
 * Mount this hook ONCE at the app root (inside `SwrProvider`). Every
 * SWR-backed page automatically gets push-driven freshness — no per-page
 * wiring required.
 *
 * Event handling:
 *   - `connected` (fired on subscribe + after reconnect): full
 *     revalidate so the UI catches up on anything that changed during
 *     the disconnect gap. EventSource auto-reconnects on TCP drop.
 *   - `tick`      : revalidate every SWR key in the cache.
 *   - `heartbeat` : ignored (idle keepalive only).
 */
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

    const revalidateAll = () => {
      // SWR's global mutate with a filter predicate returning true
      // revalidates EVERY key currently in the cache. Existing data
      // stays on screen during the re-fetch (keepPreviousData is on
      // in SwrProvider), so users never see a flash of empty.
      mutateRef.current(() => true);
    };

    const connect = () => {
      if (closed) return;
      es = new EventSource(url);

      es.addEventListener("connected", () => {
        // Initial connect OR reconnect — both invalidate everything.
        // Browser EventSource auto-reconnects on drop and re-fires the
        // `connected` event when the server's handler restarts.
        revalidateAll();
      });

      es.addEventListener("tick", () => {
        revalidateAll();
      });

      // `heartbeat` is intentionally ignored. The browser keeps the
      // connection alive on its end; the heartbeat just satisfies any
      // proxy / NAT idle timeout in between.

      es.onerror = () => {
        // EventSource auto-reconnects on most transient errors. If the
        // server is genuinely gone, we want to fail loudly in the
        // console for debugging but NOT crash the app.
        if (es?.readyState === EventSource.CLOSED) {
          // Browser gave up — manual reconnect after a short delay.
          if (!closed) {
            setTimeout(connect, 2_000);
          }
        }
      };
    };

    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, []); // intentionally no deps — subscription is process-lifetime
}
