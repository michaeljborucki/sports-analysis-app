import clsx from "clsx";

/** Label over a big mono number. `tone` colors the value by role. */
export function StatTile({
  label,
  value,
  sub,
  tone,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "edge" | "gain" | "loss" | "stale";
  className?: string;
}) {
  return (
    <div className={clsx("rounded-lg border border-border-subtle bg-bg-1 px-4 py-3", className)}>
      <div className="text-[length:var(--fs-12)] text-text-3">{label}</div>
      <div
        className={clsx(
          "tabular mt-1 text-[length:var(--fs-22)] leading-[var(--lh-22)] font-semibold",
          tone === "edge" && "text-edge",
          tone === "gain" && "text-gain",
          tone === "loss" && "text-loss",
          tone === "stale" && "text-stale",
          !tone && "text-text-1",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[length:var(--fs-12)] text-text-3">{sub}</div>}
    </div>
  );
}
