/**
 * Shared bankroll / Kelly-fraction / rounding store for /edges.
 *
 * Both the workbench (one-row deep stake calculator) and the row-level
 * StakeCell (compact preview in the table) read from this. localStorage is
 * the persistence layer; an in-process subscriber set fans out updates so
 * editing bankroll inside one workbench instantly reshades every row's
 * STAKE column.
 *
 * Cross-tab `storage` events also refresh, so two browser tabs stay in sync.
 */
"use client";
import { useSyncExternalStore } from "react";

import type { RoundIncrement } from "./stake-calc";

const KEYS = {
  bankroll: "bankroll",
  kellyFrac: "edges-kelly-frac",
  rounding: "edges-round",
} as const;

export interface EdgesPrefs {
  bankroll: number;
  kellyFrac: number;
  rounding: RoundIncrement;
}

const DEFAULTS: EdgesPrefs = {
  bankroll: 1000,
  kellyFrac: 0.25,
  rounding: 5,
};

const subs = new Set<() => void>();
let snap: EdgesPrefs = DEFAULTS;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function read(): EdgesPrefs {
  if (typeof window === "undefined") return DEFAULTS;
  const br = Number(window.localStorage.getItem(KEYS.bankroll) ?? "");
  const kf = Number(window.localStorage.getItem(KEYS.kellyFrac) ?? "");
  const rd = Number(window.localStorage.getItem(KEYS.rounding) ?? "");
  return {
    bankroll:
      Number.isFinite(br) && br > 0
        ? clamp(br, 10, 10_000_000)
        : DEFAULTS.bankroll,
    kellyFrac:
      Number.isFinite(kf) && kf > 0 && kf <= 1 ? kf : DEFAULTS.kellyFrac,
    rounding:
      rd === 1 || rd === 5 || rd === 25 || rd === 100
        ? (rd as RoundIncrement)
        : DEFAULTS.rounding,
  };
}

function refresh(): void {
  const next = read();
  if (
    next.bankroll !== snap.bankroll ||
    next.kellyFrac !== snap.kellyFrac ||
    next.rounding !== snap.rounding
  ) {
    snap = next;
    subs.forEach(fn => fn());
  }
}

if (typeof window !== "undefined") {
  snap = read();
  window.addEventListener("storage", refresh);
}

function subscribe(cb: () => void): () => void {
  subs.add(cb);
  return () => {
    subs.delete(cb);
  };
}

function getSnapshot(): EdgesPrefs {
  return snap;
}

export function useEdgesPrefs(): EdgesPrefs {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULTS);
}

export function setBankroll(v: number): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEYS.bankroll, String(v));
  refresh();
}

export function setKellyFrac(v: number): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEYS.kellyFrac, String(v));
  refresh();
}

export function setRounding(v: RoundIncrement): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEYS.rounding, String(v));
  refresh();
}
