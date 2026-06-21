import type { SportKey } from "./sports";

export type SectionScope = "global" | "per-sport";

export interface Section {
  key: string;
  label: string;
  scope: SectionScope;
}

/**
 * Nav sections. Add new entries here; the nav bar and URL routing pick them
 * up automatically.
 *   per-sport → URL is /{key}/{sport}, sport context bar rendered below nav
 *   global    → URL is /{key}, no sport context bar
 */
export const SECTIONS: Section[] = [
  { key: "dashboard", label: "Dashboard", scope: "global"    },
  { key: "odds",      label: "Odds",      scope: "per-sport" },
  { key: "props",     label: "Props",     scope: "per-sport" },
  { key: "picks",     label: "Picks",     scope: "per-sport" },
  { key: "edges",     label: "Edges",     scope: "global"    },
  { key: "accounts",  label: "Accounts",  scope: "global"    },
  { key: "bets",      label: "Bets",      scope: "global"    },
  { key: "settings",  label: "Settings",  scope: "global"    },
];

export function sectionByKey(key: string | undefined): Section | undefined {
  return SECTIONS.find(s => s.key === key);
}

export function sectionHref(section: Section, sport: SportKey): string {
  return section.scope === "per-sport"
    ? `/${section.key}/${sport}`
    : `/${section.key}`;
}
