"use client";

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function StaleBanner({ staleSeconds }: { staleSeconds: number }) {
  if (staleSeconds <= 90) return null;
  return (
    <div
      role="alert"
      className="flex items-center gap-3 bg-flash/10 border border-flash/30 text-flash px-4 py-2 rounded-md text-sm"
    >
      <span
        aria-hidden
        className="inline-block w-1.5 h-1.5 rounded-full bg-flash"
      />
      <span>
        <span className="tabular font-semibold">
          Odds last updated {formatAge(staleSeconds)} ago
        </span>{" "}
        — the fetcher may be stuck. Check{" "}
        <a
          className="underline decoration-flash/50 hover:decoration-flash"
          href="http://127.0.0.1:8000/api/health"
          target="_blank"
          rel="noreferrer"
        >
          /api/health
        </a>
        .
      </span>
    </div>
  );
}
