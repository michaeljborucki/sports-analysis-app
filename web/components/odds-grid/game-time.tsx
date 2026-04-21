"use client";
import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Renders a game's commence time in the browser's local timezone.
 *
 * SSR renders a placeholder so the markup matches the first client render
 * exactly. Once mounted we format with the browser's TZ/locale — which is
 * what the user actually wants to see, but which would hydration-mismatch
 * if we'd emitted it during SSR.
 */
export function GameTime({ commenceTime }: { commenceTime: string }) {
  const mounted = useIsMounted();
  if (!mounted) {
    return <span className="tabular">&nbsp;</span>;
  }
  const d = new Date(commenceTime);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = d.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  if (sameDay) {
    return <span className="tabular">{time}</span>;
  }
  // Different calendar day — prepend date prefix so users can distinguish
  // "today 4:11 PM" from "tomorrow 4:11 PM" at a glance.
  const dateLabel = d.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
  return (
    <span className="tabular">
      {dateLabel} · {time}
    </span>
  );
}
