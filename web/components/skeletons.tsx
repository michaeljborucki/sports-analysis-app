export function OddsGridSkeleton({
  rows = 10,
  cols = 8,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4">
        <div className="skeleton h-7 w-56 rounded-md" />
        <div className="skeleton h-3 w-16 rounded" />
      </div>
      <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
        <div className="h-9 bg-bg-1 border-b border-border-subtle flex items-center px-3 gap-6">
          <div className="skeleton h-2.5 w-12 rounded opacity-70" />
          <div className="skeleton h-2.5 w-10 rounded opacity-70" />
          {Array.from({ length: cols }).map((_, j) => (
            <div
              key={j}
              className="skeleton h-2.5 w-8 rounded opacity-70"
            />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-9 border-b border-border-subtle flex items-center px-3 gap-6"
          >
            <div className="skeleton h-3 w-32 rounded" />
            <div className="skeleton h-3 w-14 rounded" />
            {Array.from({ length: cols }).map((_, j) => (
              <div key={j} className="skeleton h-3 w-10 rounded opacity-60" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PicksTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <div className="h-9 bg-bg-1 border-b border-border-subtle flex items-center px-3 gap-6">
        {["Tier", "Game", "Pick", "Odds", "Prob", "Edge", "Stake", "Agent"].map(
          l => (
            <div
              key={l}
              className="skeleton h-2.5 w-10 rounded opacity-70"
            />
          )
        )}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-9 border-b border-border-subtle flex items-center px-3 gap-6"
        >
          <div className="skeleton h-4 w-10 rounded" />
          <div className="skeleton h-3 w-20 rounded" />
          <div className="skeleton h-3 w-28 rounded" />
          <div className="skeleton h-3 w-10 rounded" />
          <div className="skeleton h-3 w-12 rounded" />
          <div className="skeleton h-3 w-12 rounded" />
          <div className="skeleton h-3 w-8 rounded" />
          <div className="skeleton h-3 w-32 rounded" />
        </div>
      ))}
    </div>
  );
}
