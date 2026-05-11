"use client";
/**
 * Mounts the command palette once at the root layout level and installs
 * the global Cmd/Ctrl-K keyboard listener. Keep this component thin: all
 * UI lives in `command-palette.tsx`, and all command definitions live in
 * `lib/commands.ts`.
 *
 * The listener is installed on `window.keydown` with capture=false so
 * input fields can steal other keys; we only claim the K combination.
 */
import * as React from "react";

import { CommandPalette } from "./command-palette";

export function CommandPaletteMount() {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      // Cmd+K on macOS, Ctrl+K elsewhere. Don't require shift; don't
      // require any other modifier. Single `k` press alone does nothing.
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen(prev => !prev);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Expose an imperative opener via a custom event so the nav-shell chip
  // (and future triggers) can open the palette without prop drilling.
  React.useEffect(() => {
    const onOpen = (): void => setOpen(true);
    window.addEventListener("command-palette:open", onOpen);
    return () => window.removeEventListener("command-palette:open", onOpen);
  }, []);

  return <CommandPalette open={open} onOpenChange={setOpen} />;
}
