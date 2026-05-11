"use client";
/**
 * Mounts the keyboard-shortcuts overlay once at the root layout level and
 * installs the global `?` keystroke listener. Sibling of
 * `command-palette-mount.tsx`; both live in `app/layout.tsx` and listen on
 * `window.keydown` without stepping on each other — each one checks its
 * own predicates (focus-in-input, palette-open, etc.).
 *
 * Listener design notes:
 *
 *   - We listen for `key === "?"` OR `(key === "/" && shiftKey)`. US
 *     layouts send `?` as the post-shift character; some international
 *     layouts and some browser/OS combinations deliver the physical
 *     `/` + `shiftKey=true` instead. Accept both.
 *
 *   - We ignore the keystroke when focus is in an input / textarea /
 *     contentEditable. Critical: a filter field is a plausible place for
 *     a user to type a literal `?`, and stealing the character there
 *     would be infuriating.
 *
 *   - We ignore when the command palette is open. The cmdk input may
 *     deliver `?` into the search box and we should not steal focus. We
 *     detect this cheaply via `document.querySelector('[cmdk-root]')` +
 *     visibility — alternative (a shared open-state context) would be
 *     cleaner but is overkill for one check.
 *
 *   - Custom-event bridge: `window.dispatchEvent(new CustomEvent(
 *     "shortcuts:open"))` opens the overlay from anywhere. The Cmd-K
 *     palette uses this to expose a "Show keyboard shortcuts" command.
 */
import * as React from "react";

import { ShortcutOverlay } from "./shortcut-overlay";

export const SHORTCUTS_OPEN_EVENT = "shortcuts:open";

function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return true;
  if (t.isContentEditable) return true;
  return false;
}

function isCommandPaletteOpen(): boolean {
  if (typeof document === "undefined") return false;
  // cmdk stamps `cmdk-root` as a data-ish attribute on its root. Our
  // palette only mounts that node when `open === true` (see
  // `CommandPalette` early return). Presence == open.
  return document.querySelector("[cmdk-root]") != null;
}

export function ShortcutOverlayMount() {
  const [open, setOpen] = React.useState(false);

  // Global `?` keystroke listener.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const isQuestion =
        e.key === "?" || (e.key === "/" && e.shiftKey);
      if (!isQuestion) return;
      // Modifier-only presses don't count. `?` with Cmd/Ctrl/Alt is
      // almost certainly the user trying to do something else — bail.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isEditableTarget(e.target)) return;
      if (isCommandPaletteOpen()) return;
      e.preventDefault();
      setOpen(prev => !prev);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Custom-event opener so the Cmd-K palette (and future triggers) can
  // pop the overlay without prop-drilling. Mirror of the
  // `command-palette:open` pattern.
  React.useEffect(() => {
    const onOpen = (): void => setOpen(true);
    window.addEventListener(SHORTCUTS_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(SHORTCUTS_OPEN_EVENT, onOpen);
  }, []);

  return <ShortcutOverlay open={open} onOpenChange={setOpen} />;
}
