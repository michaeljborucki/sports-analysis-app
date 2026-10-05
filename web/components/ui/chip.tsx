import clsx from "clsx";

export type ChipTone = "neutral" | "edge" | "gain" | "loss" | "stale" | "live" | "sharp";

const TONES: Record<ChipTone, string> = {
  neutral: "bg-bg-2 text-text-2 border-border-subtle",
  edge: "bg-[var(--edge-10)] text-edge border-[var(--edge-25)]",
  gain: "bg-[var(--gain-10)] text-gain border-[var(--gain-25)]",
  loss: "bg-[var(--loss-10)] text-loss border-[var(--loss-25)]",
  stale: "bg-[var(--stale-10)] text-stale border-[var(--stale-25)]",
  live: "bg-[rgb(var(--live-rgb)/0.10)] text-live border-[rgb(var(--live-rgb)/0.3)]",
  sharp: "bg-[var(--sharp-20)] text-sharp border-[var(--sharp-40)]",
};

/** Small labeled chip. Tone must match the color role (spec §1). */
export function Chip({
  tone = "neutral",
  children,
  title,
  className,
}: {
  tone?: ChipTone;
  children: React.ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 h-5 px-1.5 rounded border text-[length:var(--fs-11)] font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
