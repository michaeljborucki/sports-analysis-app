"use client";
import { SWRConfig, type SWRConfiguration } from "swr";
import { fetchJson } from "./api";
import type { ReactNode } from "react";

const base: SWRConfiguration = {
  fetcher: fetchJson,
  revalidateOnFocus: true,
  keepPreviousData: true,
  dedupingInterval: 5_000,
};

export function SwrProvider({ children }: { children: ReactNode }) {
  return <SWRConfig value={base}>{children}</SWRConfig>;
}

export const intervals = {
  odds: 15_000,
  picks: 60_000,
  health: 30_000,
} as const;
