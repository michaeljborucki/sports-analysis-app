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
  return (
    <span className="tabular">
      {new Date(commenceTime).toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
      })}
    </span>
  );
}
