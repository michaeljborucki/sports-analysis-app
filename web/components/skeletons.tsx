/**
 * Loading placeholder for the odds and props grids. Mirrors the real
 * layout: a 40px segmented market strip, a 32px .dt-head row, and body rows
 * at the density-aware `--row-h` so nothing jumps when data lands.
 */
export function OddsGridSkeleton({
  rows = 10,
  cols = 8,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading prices">
      <div className="flex items-center gap-4">
        <div className="skeleton h-10 w-72 rounded-lg" />
        <div className="skeleton h-3 w-16 rounded" />
      </div>
      <div className="rounded-lg border border-border-subtle bg-bg-0 overflow-hidden">
        <div className="dt-head flex h-8 items-center gap-6 px-[var(--row-pad-x)]">
          <div className="skeleton h-2.5 w-12 rounded opacity-70" />
          <div className="skeleton h-2.5 w-10 rounded opacity-70" />
          {Array.from({ length: cols }).map((_, j) => (
            <div key={j} className="skeleton h-2.5 w-8 rounded opacity-70" />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="flex h-[var(--row-h)] items-center gap-6 border-b border-border-subtle px-[var(--row-pad-x)] last:border-b-0"
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
