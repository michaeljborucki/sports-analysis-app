/**
 * Static registry of every keyboard shortcut surfaced by the app.
 *
 * The `?` overlay (see `components/shortcut-overlay.tsx`) reads from this
 * array and renders groups in the order they first appear. No hooks, no
 * side effects — just data. Adding a new shortcut is a one-liner here,
 * assuming the actual key listener is wired elsewhere.
 *
 * Only list shortcuts that are actually wired. Do NOT advertise planned
 * shortcuts — a dead entry in this overlay is worse than no entry
 * because the user tries it, nothing happens, trust erodes.
 *
 * TODO (future waves):
 *   - `g`-prefix chord navigation (`g d` → dashboard, `g o` → odds, …).
 *     When implemented, add entries with `keys: ["G", "then", "D"]` and
 *     render "then" as a subscript between chips in the overlay.
 *   - `j` / `k` list-navigation + `/` focus-filter. Requires a shared
 *     `useListNav` hook and opt-in from list pages. Skipped in this wave
 *     because no list component currently exposes a cursor.
 */

export type ShortcutGroup = "Navigation" | "Display" | "Lists";

export interface ShortcutEntry {
  /**
   * Human-readable keystroke segments. For single combos each element is a
   * key chip (e.g. `["⌘", "K"]` → `⌘` `K`). For sequential chords insert
   * the literal string `"then"` between chips — the overlay renders it as
   * a subscript separator (e.g. `["G", "then", "D"]`).
   *
   * Mac-vs-non-Mac substitution (⌘ → Ctrl) happens in the overlay at
   * render time; store the Mac form here.
   */
  keys: string[];
  label: string;
  group: ShortcutGroup;
  /** Hide this row on non-Mac platforms. Currently unused. */
  macOnly?: boolean;
  /** Hide this row on Mac. Currently unused. */
  winOnly?: boolean;
  /**
   * `true` when the shortcut is actively wired. `false` would mean "listed
   * as planned, render dimmed" — we do NOT ship false entries in this
   * wave (see module docstring). Field exists so future agents can
   * introduce planned-shortcut rows without a schema change.
   */
  running?: boolean;
}

/**
 * Keep the ordering stable — the overlay renders groups in the order they
 * first appear here, and rows within a group in array order. Put the
 * most-common shortcuts first within each group.
 */
export const SHORTCUTS: ShortcutEntry[] = [
  // ─── Navigation ───
  {
    keys: ["⌘", "K"],
    label: "Open command palette",
    group: "Navigation",
    running: true,
  },
  {
    keys: ["?"],
    label: "Show keyboard shortcuts",
    group: "Navigation",
    running: true,
  },

  // ─── Display ───
  {
    keys: ["⌘", "Shift", "D"],
    label: "Cycle row density (compact / comfortable / spacious)",
    group: "Display",
    running: true,
  },
];

/** Render order for groups. Groups without any entries are skipped. */
export const SHORTCUT_GROUP_ORDER: ShortcutGroup[] = [
  "Navigation",
  "Display",
  "Lists",
];

/**
 * Replace the Mac command glyph with `Ctrl` on non-Mac so the overlay
 * shows the keystrokes a given user will actually press. Called per-row
 * at render time.
 */
export function remapKeysForPlatform(
  keys: string[],
  isMac: boolean
): string[] {
  if (isMac) return keys;
  return keys.map(k => (k === "⌘" ? "Ctrl" : k));
}
