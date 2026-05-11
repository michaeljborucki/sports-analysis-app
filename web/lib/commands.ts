/**
 * Command registry for the Cmd/Ctrl-K palette.
 *
 * Commands are registered statically in `COMMANDS` and executed via
 * `cmd.run(ctx)` — the context is assembled in `CommandPaletteMount` from
 * the same hooks the nav shell uses (useLiveFilter, useDensity, useRouter).
 *
 * Adding a command is a one-liner here; the palette picks it up without
 * code changes. Grouping is driven by the `group` field; cmdk's default
 * filter (command-score) handles fuzzy matching against label + keywords.
 */
import * as React from "react";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { ArrowRight, Filter, Keyboard, Search, Zap } from "lucide-react";

import type { LiveStatus } from "@/components/live-status-filter";
import type { Density } from "@/lib/use-density";
import { SPORTS, type SportKey } from "@/lib/sports";

// ─────────────────────────── Types ───────────────────────────

export type CommandGroup = "Navigate" | "Filter" | "Action" | "Search";

export interface CommandContext {
  router: AppRouterInstance;
  setLiveFilter: (v: LiveStatus) => void;
  setDensity: (v: Density) => void;
  close: () => void;
}

export interface Command {
  id: string;
  label: string;
  /** Right-aligned subtext (e.g. a current-state chip, a shortcut). */
  hint?: string;
  group: CommandGroup;
  /** Per-command icon override; otherwise a group-default is rendered. */
  icon?: React.ReactNode;
  /** Extra keywords to feed cmdk's fuzzy matcher. */
  keywords?: string[];
  run: (ctx: CommandContext) => void | Promise<void>;
}

/** Global custom event that pages listen to for manual refresh. */
export const REFRESH_ALL_EVENT = "edges:refresh-all";

// Default icons rendered when a command doesn't supply its own.
export const GROUP_ICONS: Record<CommandGroup, React.ReactNode> = {
  Navigate: React.createElement(ArrowRight, { size: 14 }),
  Filter: React.createElement(Filter, { size: 14 }),
  Action: React.createElement(Zap, { size: 14 }),
  Search: React.createElement(Search, { size: 14 }),
};

// ─────────────────────── Command builders ───────────────────────

// Sports available in the nav for per-sport sections. The section registry
// says Props is NBA/MLB/NHL only (tennis/ncaa props aren't wired); Odds
// and Picks support every sport in SPORTS. Edges is global.
const PROP_SPORTS: SportKey[] = ["mlb", "nba", "nhl"];
const NAV_SPORTS: SportKey[] = ["mlb", "nba", "nhl", "tennis"];

function navCommand(
  id: string,
  label: string,
  path: string,
  keywords: string[] = []
): Command {
  return {
    id,
    label,
    group: "Navigate",
    keywords,
    run: ({ router, close }) => {
      router.push(path);
      close();
    },
  };
}

function liveFilterCommand(value: LiveStatus, label: string): Command {
  return {
    id: `filter.live.${value}`,
    label: `Live filter: ${label}`,
    group: "Filter",
    hint: value.toUpperCase(),
    keywords: ["live", "pre", "all", "status", value],
    run: ({ setLiveFilter, close }) => {
      setLiveFilter(value);
      close();
    },
  };
}

function densityCommand(value: Density): Command {
  const label = value.charAt(0).toUpperCase() + value.slice(1);
  return {
    id: `action.density.${value}`,
    label: `Density: ${label}`,
    group: "Action",
    hint: label,
    keywords: ["density", "spacing", "row height", value, "table"],
    run: ({ setDensity, close }) => {
      setDensity(value);
      close();
    },
  };
}

// ─────────────────────── Static registry ───────────────────────

export const COMMANDS: Command[] = [
  // ────── Navigate: top-level sections ──────
  navCommand("nav.dashboard", "Go to Dashboard", "/dashboard", [
    "home",
    "overview",
  ]),
  navCommand("nav.settings", "Go to Settings", "/settings", [
    "preferences",
    "config",
  ]),

  // ────── Navigate: Odds (per-sport) ──────
  ...NAV_SPORTS.map(s =>
    navCommand(
      `nav.odds.${s}`,
      `Go to Odds — ${SPORTS[s].label}`,
      `/odds/${s}`,
      ["odds", "lines", s, SPORTS[s].label.toLowerCase()]
    )
  ),

  // ────── Navigate: Props (NBA / MLB / NHL) ──────
  ...PROP_SPORTS.map(s =>
    navCommand(
      `nav.props.${s}`,
      `Go to Props — ${SPORTS[s].label}`,
      `/props/${s}`,
      ["props", "players", s, SPORTS[s].label.toLowerCase()]
    )
  ),

  // ────── Navigate: Picks (per-sport) ──────
  ...NAV_SPORTS.map(s =>
    navCommand(
      `nav.picks.${s}`,
      `Go to Picks — ${SPORTS[s].label}`,
      `/picks/${s}`,
      ["picks", "bets", s, SPORTS[s].label.toLowerCase()]
    )
  ),

  // ────── Navigate: Edges (mode-scoped) ──────
  navCommand("nav.edges", "Go to Edges", "/edges", [
    "edges",
    "opportunities",
  ]),
  navCommand(
    "nav.edges.arb",
    "Go to Edges — Arbitrage",
    "/edges?modes=arb",
    ["arbitrage", "arb", "edges"]
  ),
  navCommand(
    "nav.edges.low_hold",
    "Go to Edges — Low Hold",
    "/edges?modes=low_hold",
    ["low hold", "low-hold", "lh", "edges"]
  ),
  navCommand(
    "nav.edges.ev",
    "Go to Edges — +EV",
    "/edges?modes=ev",
    ["ev", "plus ev", "expected value", "edges"]
  ),
  navCommand(
    "nav.edges.free_bet",
    "Go to Edges — Free Bets",
    "/edges?modes=free_bet",
    ["free bet", "freebet", "fb", "promo", "edges"]
  ),

  // ────── Filter: live status ──────
  liveFilterCommand("all", "All"),
  liveFilterCommand("pre", "Pre"),
  liveFilterCommand("live", "Live"),

  // ────── Filter: fetcher (direct API call — no shared hook) ──────
  {
    id: "filter.fetcher.on",
    label: "Fetcher: on",
    group: "Filter",
    hint: "START",
    keywords: ["fetcher", "poll", "live", "start", "on", "resume"],
    run: async ({ close }) => {
      // TODO: wire this to a shared useFetcher() hook once exposed by the
      // fetcher-toggle component. For now we POST directly to keep the
      // palette functional.
      try {
        const base =
          process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
        await fetch(`${base}/api/fetcher/start`, { method: "POST" });
      } catch {
        /* swallow — fetcher-toggle will surface errors via its SWR status */
      }
      close();
    },
  },
  {
    id: "filter.fetcher.off",
    label: "Fetcher: off",
    group: "Filter",
    hint: "STOP",
    keywords: ["fetcher", "freeze", "stop", "off", "pause"],
    run: async ({ close }) => {
      try {
        const base =
          process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
        await fetch(`${base}/api/fetcher/stop`, { method: "POST" });
      } catch {
        /* swallow */
      }
      close();
    },
  },

  // ────── Action: refresh-all (fire custom event) ──────
  {
    id: "action.refresh",
    label: "Refresh all",
    group: "Action",
    hint: "R",
    keywords: ["refresh", "reload", "mutate", "update"],
    run: ({ close }) => {
      // Pages that want to participate listen for `edges:refresh-all` and
      // call their SWR `mutate()`. If no page is listening, nothing
      // breaks — this is a soft-refresh event.
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(REFRESH_ALL_EVENT));
      }
      close();
    },
  },

  // ────── Action: density cycling ──────
  densityCommand("compact"),
  densityCommand("comfortable"),
  densityCommand("spacious"),

  // ────── Action: shortcuts overlay ──────
  // Bridges the palette to the `?` overlay. Dispatches a custom event
  // that `ShortcutOverlayMount` listens for; keeps the two discovery
  // surfaces decoupled (no shared context, no prop drilling).
  {
    id: "action.shortcuts",
    label: "Show keyboard shortcuts",
    group: "Action",
    hint: "?",
    icon: React.createElement(Keyboard, { size: 14 }),
    keywords: ["shortcuts", "keyboard", "keys", "hotkeys", "help", "?"],
    run: ({ close }) => {
      close();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("shortcuts:open"));
      }
    },
  },
];

/**
 * Runtime-extensible helper. We export both the static array (for simple
 * readers) and a getter — future code can append to the array before the
 * palette mounts, or we can swap in a subscriber pattern later without a
 * rename.
 */
export function getCommands(): Command[] {
  return COMMANDS;
}
