"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * Density mode — drives the --row-h / --row-pad-y / --row-pad-x CSS vars
 * declared in globals.css under `html[data-density="…"]`. Persisted in
 * localStorage under `density_v1` and mirrored onto
 * `document.documentElement.dataset.density` so the CSS vars cascade to the
 * whole tree.
 *
 * The hook also installs a single global keyboard shortcut (Cmd/Ctrl +
 * Shift + D) that cycles compact → comfortable → spacious → compact. The
 * listener is added ONCE across the app regardless of how many components
 * read the current density — an internal module-level ref-count guards
 * against duplicate listeners.
 */

export type Density = "compact" | "comfortable" | "spacious";

export const DENSITY_CYCLE: readonly Density[] = [
  "compact",
  "comfortable",
  "spacious",
] as const;

const STORAGE_KEY = "density_v1";
const DEFAULT_DENSITY: Density = "comfortable";

function isDensity(v: unknown): v is Density {
  return v === "compact" || v === "comfortable" || v === "spacious";
}

function readStored(): Density {
  if (typeof window === "undefined") return DEFAULT_DENSITY;
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (isDensity(v)) return v;
  } catch {}
  return DEFAULT_DENSITY;
}

// Module-level subscriber set: every `useDensity` instance subscribes via
// `useSyncExternalStore` so a write from any caller (toggle click, hotkey,
// storage event from another tab) re-renders every reader without React
// context ceremony.
const subscribers = new Set<() => void>();
let current: Density | null = null;

function emit(): void {
  for (const cb of subscribers) cb();
}

function writeDensity(value: Density): void {
  if (typeof document === "undefined") return;
  current = value;
  document.documentElement.dataset.density = value;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {}
  emit();
}

// Bootstrap: on first client-side access, hydrate `current` from storage
// and mirror it onto <html> so CSS vars apply. layout.tsx ships with
// `data-density="comfortable"` as an SSR default — we only overwrite if
// the user has a saved preference.
function bootstrap(): void {
  if (typeof document === "undefined") return;
  if (current != null) return;
  const stored = readStored();
  current = stored;
  if (stored !== DEFAULT_DENSITY) {
    document.documentElement.dataset.density = stored;
  }
}

// Global hotkey installer. Installed once, reference-counted so it
// detaches when nothing is listening (matters for HMR in dev; negligible
// in prod because at least one consumer is always mounted).
let hotkeyRefCount = 0;
let hotkeyDetach: (() => void) | null = null;

function installHotkeyIfNeeded(): void {
  if (typeof window === "undefined") return;
  if (hotkeyRefCount++ > 0) return;
  const onKey = (e: KeyboardEvent): void => {
    // Cmd+Shift+D on macOS, Ctrl+Shift+D elsewhere. `metaKey` on Mac, but
    // allow Ctrl too so the shortcut works on a Mac keyboard mapped to a
    // non-Mac OS (dual-boot / remote-desktop). No harm — shortcut is not
    // destructive.
    if (!e.shiftKey) return;
    if (!(e.metaKey || e.ctrlKey)) return;
    if (e.key !== "D" && e.key !== "d") return;
    // Don't steal focus from editable fields.
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
      return;
    }
    e.preventDefault();
    const cur = current ?? readStored();
    const idx = DENSITY_CYCLE.indexOf(cur);
    const next = DENSITY_CYCLE[(idx + 1) % DENSITY_CYCLE.length];
    writeDensity(next);
  };
  window.addEventListener("keydown", onKey);
  hotkeyDetach = () => window.removeEventListener("keydown", onKey);
}

function uninstallHotkeyIfNeeded(): void {
  if (--hotkeyRefCount > 0) return;
  hotkeyDetach?.();
  hotkeyDetach = null;
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

function getSnapshot(): Density {
  if (current == null) bootstrap();
  return current ?? DEFAULT_DENSITY;
}

// SSR snapshot: always return the default. Layout ships with that default
// so the first paint matches.
function getServerSnapshot(): Density {
  return DEFAULT_DENSITY;
}

/**
 * Read the current density and subscribe to changes.
 *
 * @param options.installHotkey — when true, installs the global
 *   Cmd/Ctrl+Shift+D hotkey for the lifetime of this hook. Exactly one
 *   caller per app should opt in (we wire it through the DensityToggle
 *   which renders inside Settings). Multiple callers with the flag set is
 *   safe — the listener is ref-counted.
 */
export function useDensity(options?: { installHotkey?: boolean }): {
  density: Density;
  setDensity: (v: Density) => void;
  cycleDensity: () => void;
} {
  const density = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setDensity = useCallback((v: Density) => {
    writeDensity(v);
  }, []);

  const cycleDensity = useCallback(() => {
    const cur = current ?? readStored();
    const idx = DENSITY_CYCLE.indexOf(cur);
    const next = DENSITY_CYCLE[(idx + 1) % DENSITY_CYCLE.length];
    writeDensity(next);
  }, []);

  useEffect(() => {
    if (!options?.installHotkey) return;
    installHotkeyIfNeeded();
    return () => uninstallHotkeyIfNeeded();
  }, [options?.installHotkey]);

  // Cross-tab sync: when another tab writes `density_v1`, mirror it.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent): void => {
      if (e.key !== STORAGE_KEY) return;
      if (!isDensity(e.newValue)) return;
      if (e.newValue === current) return;
      current = e.newValue;
      document.documentElement.dataset.density = e.newValue;
      emit();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return { density, setDensity, cycleDensity };
}
