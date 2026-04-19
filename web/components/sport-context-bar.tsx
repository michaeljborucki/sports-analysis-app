"use client";
import { SportSwitcher } from "./sport-switcher";

/**
 * Sub-nav that only renders on sections scoped to a single sport. Holds the
 * sport picker and leaves room for section-specific meta later (games count,
 * last-run timestamp, etc.).
 */
export function SportContextBar() {
  return (
    <div className="border-b border-border-subtle/70 bg-bg-0/80">
      <div className="max-w-[1600px] mx-auto px-6 py-2 flex items-center gap-4">
        <SportSwitcher />
      </div>
    </div>
  );
}
