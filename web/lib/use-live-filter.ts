"use client";
import { useCallback, useEffect, useState } from "react";
import type { LiveStatus } from "@/components/live-status-filter";


const STORAGE_KEY = "live_filter_v1";
const DEFAULT_VALUE: LiveStatus = "all";
const CHANGE_EVENT = "betting-site:live-filter-change";


/**
 * Global Live / Pre / All filter state. Backed by localStorage so every page
 * sees the same value, and a DOM `CustomEvent` so multiple mounted
 * subscribers (e.g. the nav shell toggle and an open page) stay in sync
 * within the same tab without a page reload.
 */
export function useLiveFilter(): {
  value: LiveStatus;
  setValue: (v: LiveStatus) => void;
} {
  const [value, setLocal] = useState<LiveStatus>(DEFAULT_VALUE);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw === "all" || raw === "pre" || raw === "live") setLocal(raw);
    } catch {}

    const onChange = (e: Event) => {
      const detail = (e as CustomEvent).detail as LiveStatus | undefined;
      if (detail === "all" || detail === "pre" || detail === "live") {
        setLocal(detail);
      }
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      const v = e.newValue;
      if (v === "all" || v === "pre" || v === "live") setLocal(v);
    };

    window.addEventListener(CHANGE_EVENT, onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const setValue = useCallback((next: LiveStatus) => {
    setLocal(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {}
    // Broadcast to other mounted useLiveFilter consumers in this tab so
    // they re-render immediately. Cross-tab sync still rides the storage
    // event above.
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: next }));
  }, []);

  return { value, setValue };
}
