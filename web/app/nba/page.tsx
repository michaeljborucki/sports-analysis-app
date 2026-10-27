"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";

import { NbaGamesGrid } from "@/components/nba/nba-games-grid";
import { NbaSgp } from "@/components/nba/nba-sgp";
import { NbaTeamsTable } from "@/components/nba/nba-teams-table";
import { RefreshButton } from "@/components/refresh-button";
import { ErrorBanner, PageHeader, Segmented } from "@/components/ui";
import { apiPaths } from "@/lib/api";
import { fmtDay, isDay, shiftDay, type NbaPredictionsResponse, type SgpResponse } from "@/lib/nba";

type View = "games" | "teams" | "sgp";

const VIEWS: { value: View; label: string }[] = [
  { value: "games", label: "Games" },
  { value: "teams", label: "Teams" },
  { value: "sgp", label: "SGP" },
];

export default function NbaPage() {
  return (
    <Suspense fallback={<NbaLoading />}>
      <NbaPageInner />
    </Suspense>
  );
}

function NbaPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewParam = searchParams.get("view");
  const view: View = viewParam === "teams" || viewParam === "sgp" ? viewParam : "games";
  const dateParam = searchParams.get("date");
  const date = isDay(dateParam) ? dateParam : undefined;

  const { data, error, isLoading, isValidating, mutate } = useSWR<NbaPredictionsResponse>(
    apiPaths.nbaPredictions(date),
    { refreshInterval: 300_000 },
  );

  const sgp = useSWR<SgpResponse>(view === "sgp" ? apiPaths.nbaSgp(date) : null, {
    refreshInterval: 300_000,
  });

  const shownDate = data?.date ?? date;
  const go = (next: { date?: string; view?: View }) => {
    const qs = new URLSearchParams();
    const d = next.date ?? shownDate;
    const v = next.view ?? view;
    if (d && d !== data?.today) qs.set("date", d);
    if (v !== "games") qs.set("view", v);
    const q = qs.toString();
    router.push(`/nba${q ? `?${q}` : ""}`);
  };

  const lastSeasonTeams = data ? data.teams.filter(t => t.source === "last_season").length : 0;

  const description = data ? (
    <>
      Possession-efficiency projections from{" "}
      <span className="tabular">{data.games_used}</span> completed {data.season - 1}–{String(data.season).slice(2)}{" "}
      regular-season games before {fmtDay(data.date)}
      {lastSeasonTeams > 0 && (
        <>
          {" "}· <span className="tabular">{lastSeasonTeams}</span>
          {lastSeasonTeams === 1 ? " team" : " teams"} on last season&apos;s{" "}
          <span className="tabular">{data.prior_games_used}</span> games
        </>
      )}
      {data.games_skipped > 0 && (
        <> (<span className="tabular">{data.games_skipped}</span> skipped: no box score)</>
      )}
    </>
  ) : (
    "Possession-efficiency projections for every NBA game"
  );

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        title="NBA"
        description={description}
        inline={
          <div className="flex items-center gap-3">
            <DayStepper day={shownDate} today={data?.today} onChange={d => go({ date: d })} />
            <Segmented<View>
              ariaLabel="NBA view"
              size="sm"
              value={view}
              onChange={v => go({ view: v })}
              options={VIEWS}
            />
          </div>
        }
        actions={
          <RefreshButton
            onRefresh={() => {
              mutate();
              if (view === "sgp") sgp.mutate();
            }}
            isValidating={isValidating || sgp.isValidating}
          />
        }
      />

      {view !== "sgp" && (
        <p className="mb-4 max-w-3xl text-[length:var(--fs-13)] text-text-3">
          Each team&apos;s score = average of <span className="text-text-2">pace × its offensive efficiency</span> and{" "}
          <span className="text-text-2">pace × the opponent&apos;s defensive efficiency</span>. Pace = possessions per
          game (FGA − OREB + TOV + 0.44 × FTA); efficiency = points per possession (defensive: points allowed ÷
          opponent possessions). Teams use last season&apos;s numbers until they have{" "}
          {data?.min_current_games ?? 10} games this season. No home-court adjustment.
        </p>
      )}

      {error && (
        <ErrorBanner
          tone="loss"
          title="NBA projections are unavailable (ESPN or the API server)."
          details={String(error)}
          className="mb-5"
        />
      )}
      {isLoading && !data && <NbaLoading />}
      {data && view === "games" && (
        <NbaGamesGrid games={data.games} date={data.date} minGames={data.min_current_games} />
      )}
      {data && view === "teams" && <NbaTeamsTable teams={data.teams} minGames={data.min_current_games} />}
      {view === "sgp" && sgp.error && (
        <ErrorBanner
          tone="loss"
          title="The SGP screener is unavailable (ESPN or the API server)."
          details={String(sgp.error)}
          className="mb-5"
        />
      )}
      {view === "sgp" && !sgp.data && !sgp.error && <NbaLoading />}
      {view === "sgp" && sgp.data && <NbaSgp data={sgp.data} />}
    </div>
  );
}

function DayStepper({
  day,
  today,
  onChange,
}: {
  day: string | undefined;
  today: string | undefined;
  onChange: (d: string) => void;
}) {
  const btn =
    "inline-flex h-7 w-7 items-center justify-center rounded border border-border-subtle text-text-2 transition-colors hover:text-text-1 disabled:opacity-40";
  return (
    <div className="flex items-center gap-1.5" aria-label="Day">
      <button
        type="button"
        className={btn}
        aria-label="Previous day"
        disabled={!day}
        onClick={() => day && onChange(shiftDay(day, -1))}
      >
        ‹
      </button>
      <span className="min-w-[7.5rem] text-center text-[length:var(--fs-13)] text-text-1">
        <span className="tabular">{day ? fmtDay(day) : "…"}</span>
        {day != null && day === today && <span className="text-text-3"> · today</span>}
      </span>
      <button
        type="button"
        className={btn}
        aria-label="Next day"
        disabled={!day}
        onClick={() => day && onChange(shiftDay(day, 1))}
      >
        ›
      </button>
    </div>
  );
}

function NbaLoading() {
  return (
    <div aria-label="Loading NBA projections" className="grid gap-4">
      <div className="skeleton h-16 rounded-lg" />
      <div className="skeleton h-96 rounded-lg" />
    </div>
  );
}
