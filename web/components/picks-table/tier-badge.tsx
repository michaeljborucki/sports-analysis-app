import clsx from "clsx";
import type { PickTier } from "@/lib/api";

const TIER_CLASSES: Record<string, string> = {
  high: "bg-price-up/15 text-price-up",
  sweet: "bg-violet-accent/15 text-violet-accent",
  lean: "bg-flash/15 text-flash",
};

const TIER_LABELS: Record<string, string> = {
  high: "High",
  sweet: "Sweet",
  lean: "Lean",
};

export function TierBadge({ tier }: { tier: PickTier }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide",
        TIER_CLASSES[tier]
      )}
    >
      {TIER_LABELS[tier]}
    </span>
  );
}
