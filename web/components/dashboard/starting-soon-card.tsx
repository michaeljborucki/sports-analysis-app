"use client";
import { useRouter } from "next/navigation";

import type { Game } from "@/lib/api";
import { Chip, Panel } from "@/components/ui";

import { StartsCell, sportLabel } from "./best-now-panel";
import { useNow } from "./use-now";

/**
 * Next games in the dashboard's 3-hour window. Each row opens that sport's
 * odds page (event deep links aren't routed yet).
 */
export function StartingSoonCard({
  games,
  onRefresh,
}: {
  games: Game[];
  onRefresh: () => void;
}) {
  const router = useRouter();
  const now = useNow();
  const visible = games.slice(0, 8);

  return (
    <Panel
      title="Starting soon"
      actions={<span className="text-[length:var(--fs-12)] text-text-3">Next 3 hours</span>}
    >
      {visible.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="text-[length:var(--fs-14)] font-medium text-text-1">
            Nothing starts in the next 3 hours
          </p>
          <p className="mt-1 text-[length:var(--fs-13)] text-text-3">
            Covers every enabled sport.
          </p>
          <button
            type="button"
            onClick={onRefresh}
            className="mt-3 h-8 rounded-md border border-border-subtle bg-bg-2 px-3 text-[length:var(--fs-13)] text-text-2 hover:text-text-1"
          >
            Refresh
          </button>
        </div>
      ) : (
        <table className="w-full border-collapse">
          <tbody>
            {visible.map(g => {
              const sport = g.sport_key ?? "mlb";
              return (
                <tr
                  key={g.event_id}
                  className="dt-row cursor-pointer last:border-b-0"
                  onClick={() => router.push(`/odds/${sport}`)}
                >
                  <td className="dt-td w-0 pr-0">
                    <Chip>{sportLabel(sport)}</Chip>
                  </td>
                  <td className="dt-td max-w-0 w-full">
                    <span className="block truncate text-text-1">
                      {g.away_team} <span className="text-text-3">at</span> {g.home_team}
                    </span>
                  </td>
                  <td className="dt-td text-right whitespace-nowrap">
                    {now != null ? <StartsCell iso={g.commence_time} now={now} /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
