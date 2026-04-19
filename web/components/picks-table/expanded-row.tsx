import type { Pick } from "@/lib/api";

export function ExpandedRow({ pick }: { pick: Pick }) {
  return (
    <div className="border-l-2 border-accent pl-4 py-3 bg-bg-1/50 text-xs">
      <div className="flex gap-4 mb-2 flex-wrap">
        {pick.stats?.map(s => (
          <span key={s.label} className="text-text-2">
            {s.label}{" "}
            <span className="text-text-1 font-semibold tabular">{s.value}</span>
          </span>
        ))}
      </div>
      <p className="text-text-2 leading-relaxed max-w-3xl">{pick.reasoning}</p>
    </div>
  );
}
