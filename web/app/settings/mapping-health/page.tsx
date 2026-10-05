"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { ChevronLeft, Search } from "lucide-react";

import { fetchJson } from "@/lib/api";
import { Chip, ErrorBanner, PageHeader, Panel } from "@/components/ui";
import { useIsMounted } from "@/lib/use-is-mounted";
import { useNow } from "@/components/dashboard/use-now";

type Issue = {
  identity: string; kind: string; sport: string; source: string;
  event: string; raw_name: string; market: string; candidates: string[];
  first_seen: string; last_seen: string; hits: number; resolved: number;
};

function fmt(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function MappingHealthPage() {
  const mounted = useIsMounted();
  const now = useNow();
  const { data, error, isLoading } = useSWR<{ issues: Issue[]; total: number; last_player_check: string | null }>(
    "/api/mapping-health", fetchJson, { refreshInterval: 30000 },
  );
  const [showHistory, setShowHistory] = useState(false);
  const [search, setSearch] = useState("");
  const issues = (data?.issues ?? []).filter(i =>
    (showHistory || (!i.resolved && (now == null || now - Date.parse(i.last_seen) < 15 * 60000))) &&
    `${i.sport} ${i.raw_name} ${i.kind} ${i.market}`.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col">
      <Link
        href="/settings"
        className="mb-2 inline-flex w-fit items-center gap-1 text-[length:var(--fs-13)] text-text-2 hover:text-text-1"
      >
        <ChevronLeft size={14} aria-hidden />
        Settings
      </Link>
      <PageHeader
        title="Mapping health"
        description="Unresolved observations from the last 15 minutes. Player checks run every minute; team and stat checks run when Coral33 refreshes. Candidates are suggestions only, and missing coverage may mean a book doesn't offer that player or stat."
      >
        <div className="flex flex-wrap items-center gap-4">
          <label className="relative block">
            <Search size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-3" />
            <input
              aria-label="Filter mapping issues"
              placeholder="Filter sport, player, team or market"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-8 w-80 max-w-full rounded-md border border-border-subtle bg-bg-2 pl-8 pr-3 text-[length:var(--fs-13)] text-text-1 placeholder:text-text-3 focus:border-text-3"
            />
          </label>
          <label className="inline-flex cursor-pointer items-center gap-2 text-[length:var(--fs-13)] text-text-2">
            <input
              type="checkbox"
              checked={showHistory}
              onChange={e => setShowHistory(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--color-text-1)]"
            />
            Include older and resolved issues
          </label>
        </div>
      </PageHeader>

      <div className="flex flex-col gap-4">
        {error && <ErrorBanner title="Couldn't load mapping diagnostics. Retrying automatically." details={String(error)} />}
        {isLoading && <div className="skeleton h-48 rounded-lg" aria-label="Loading mapping diagnostics" />}

        {data && (
          <Panel
            title="Issues"
            actions={
              <span className="text-[length:var(--fs-12)] text-text-3">
                <span className="tabular">{issues.length}</span> shown of{" "}
                <span className="tabular">{data.total.toLocaleString()}</span> recorded (latest 1,000 available). Last player check{" "}
                {data.last_player_check ? (
                  <span className="tabular">{mounted ? fmt(data.last_player_check) : ""}</span>
                ) : (
                  "not yet completed"
                )}
              </span>
            }
            bodyClassName="overflow-x-auto"
          >
            {!issues.length ? (
              <p className="px-4 py-10 text-center text-[length:var(--fs-13)] text-text-3">
                No matching recent issues recorded. This doesn&rsquo;t guarantee every source market is covered.
              </p>
            ) : (
              <table className="w-full min-w-[980px] border-collapse">
                <thead className="dt-head">
                  <tr>
                    <th className="dt-th">Status</th>
                    <th className="dt-th">Source</th>
                    <th className="dt-th">Raw name</th>
                    <th className="dt-th">Event and market</th>
                    <th className="dt-th">Candidates</th>
                    <th className="dt-th">Seen</th>
                    <th className="dt-th text-right">Occurrences</th>
                  </tr>
                </thead>
                <tbody>
                  {issues.map(i => (
                    <tr key={i.identity} className="dt-row last:border-b-0">
                      <td className="dt-td align-top">
                        <div className="flex flex-col items-start gap-1">
                          <Chip tone={i.resolved ? "neutral" : "stale"}>{i.resolved ? "Resolved" : "Observed"}</Chip>
                          <Chip>{i.kind.replaceAll("_", " ")}</Chip>
                        </div>
                      </td>
                      <td className="dt-td align-top">
                        <div className="text-text-1">{i.source}</div>
                        <div className="text-[length:var(--fs-12)] text-text-3">{i.sport}</div>
                      </td>
                      <td className="dt-td align-top font-medium text-text-1">{i.raw_name}</td>
                      <td className="dt-td align-top max-w-[320px]">
                        <div className="break-words text-text-1">{i.event || "Unknown event"}</div>
                        <div className="text-[length:var(--fs-12)] text-text-3">{i.market}</div>
                      </td>
                      <td className="dt-td align-top text-text-2">
                        {i.candidates.join(", ") || <span className="text-text-3">No candidate</span>}
                      </td>
                      <td className="dt-td align-top whitespace-nowrap text-[length:var(--fs-12)] text-text-3">
                        {mounted && (
                          <>
                            <div>First <span className="tabular text-text-2">{fmt(i.first_seen)}</span></div>
                            <div>Last <span className="tabular text-text-2">{fmt(i.last_seen)}</span></div>
                          </>
                        )}
                      </td>
                      <td className="dt-td align-top text-right">
                        <span className="tabular text-text-1">{i.hits.toLocaleString()}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}
