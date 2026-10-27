"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";

import { CfbGamesGrid } from "@/components/cfb/cfb-games-grid";
import { CfbTeamsTable } from "@/components/cfb/cfb-teams-table";
import { RefreshButton } from "@/components/refresh-button";
import { ErrorBanner, PageHeader, Segmented } from "@/components/ui";
import { apiPaths } from "@/lib/api";
import type { CfbDivision, CfbPredictionsResponse } from "@/lib/cfb";

type View = "games" | "teams";

const VIEWS: { value: View; label: string }[] = [
  { value: "games", label: "Games" },
  { value: "teams", label: "Teams" },
];

type DivisionFilter = "all" | CfbDivision;

const DIVISION_FILTERS: { value: DivisionFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "fbs", label: "FBS" },
  { value: "fcs", label: "FCS" },
];

const LAST_REGULAR_WEEK = 15;

export default function CfbPage() {
  return (
    <Suspense fallback={<CfbLoading />}>
      <CfbPageInner />
    </Suspense>
  );
}

function CfbPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const view: View = searchParams.get("view") === "teams" ? "teams" : "games";
  const divParam = searchParams.get("div");
  const div: DivisionFilter = divParam === "fbs" || divParam === "fcs" ? divParam : "all";
  const weekParam = Number(searchParams.get("week"));
  const week = Number.isInteger(weekParam) && weekParam >= 1 ? weekParam : undefined;

  const { data, error, isLoading, isValidating, mutate } = useSWR<CfbPredictionsResponse>(
    apiPaths.cfbPredictions(week),
    { refreshInterval: 300_000 },
  );

  const shownWeek = data?.week ?? week;
  const go = (next: { week?: number; view?: View; div?: DivisionFilter }) => {
    const qs = new URLSearchParams();
    const w = next.week ?? shownWeek;
    const v = next.view ?? view;
    const d = next.div ?? div;
    if (w && w !== data?.current_week) qs.set("week", String(w));
    if (v !== "games") qs.set("view", v);
    if (d !== "all") qs.set("div", d);
    const q = qs.toString();
    router.push(`/cfb${q ? `?${q}` : ""}`);
  };

  const games = data ? data.games.filter(g => div === "all" || g.division === div) : [];
  const teams = data ? data.teams.filter(t => div === "all" || t.division === div) : [];

  const description = data ? (
    <>
      Points-per-play projections from{" "}
      <span className="tabular">{data.games_used}</span> completed {data.season} games before
      week <span className="tabular">{data.week}</span>
      {data.games_skipped > 0 && (
        <> (<span className="tabular">{data.games_skipped}</span> skipped: no box score)</>
      )}
    </>
  ) : (
    "Points-per-play projections for every FBS and FCS game"
  );

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        title="College Football"
        description={description}
        inline={
          <div className="flex items-center gap-3">
            <WeekStepper
              week={shownWeek}
              current={data?.current_week}
              onChange={w => go({ week: w })}
            />
            <Segmented<View>
              ariaLabel="CFB view"
              size="sm"
              value={view}
              onChange={v => go({ view: v })}
              options={VIEWS}
            />
            <Segmented<DivisionFilter>
              ariaLabel="Division"
              size="sm"
              value={div}
              onChange={d => go({ div: d })}
              options={DIVISION_FILTERS}
            />
          </div>
        }
        actions={<RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />}
      />

      <p className="mb-4 max-w-3xl text-[length:var(--fs-13)] text-text-3">
        Each team&apos;s score = average of <span className="text-text-2">plays × its offensive PPP</span> and{" "}
        <span className="text-text-2">plays × the opponent&apos;s defensive PPP</span>. Plays = season-average
        pass + rush attempts per game; PPP = points ÷ offensive plays (defensive: points allowed ÷ opponent
        plays). No home-field or opponent adjustment.
      </p>

      {error && (
        <ErrorBanner
          tone="loss"
          title="College football projections are unavailable (ESPN or the API server)."
          details={String(error)}
          className="mb-5"
        />
      )}
      {isLoading && !data && <CfbLoading />}
      {data && view === "games" && <CfbGamesGrid games={games} week={data.week} />}
      {data && view === "teams" && <CfbTeamsTable teams={teams} />}
    </div>
  );
}

function WeekStepper({
  week,
  current,
  onChange,
}: {
  week: number | undefined;
  current: number | undefined;
  onChange: (w: number) => void;
}) {
  const btn =
    "inline-flex h-7 w-7 items-center justify-center rounded border border-border-subtle text-text-2 transition-colors hover:text-text-1 disabled:opacity-40";
  return (
    <div className="flex items-center gap-1.5" aria-label="Week">
      <button
        type="button"
        className={btn}
        aria-label="Previous week"
        disabled={!week || week <= 1}
        onClick={() => week && onChange(week - 1)}
      >
        ‹
      </button>
      <span className="min-w-[5.5rem] text-center text-[length:var(--fs-13)] text-text-1">
        Week <span className="tabular">{week ?? "…"}</span>
        {week != null && week === current && <span className="text-text-3"> · now</span>}
      </span>
      <button
        type="button"
        className={btn}
        aria-label="Next week"
        disabled={!week || week >= LAST_REGULAR_WEEK}
        onClick={() => week && onChange(week + 1)}
      >
        ›
      </button>
    </div>
  );
}

function CfbLoading() {
  return (
    <div aria-label="Loading college football projections" className="grid gap-4">
      <div className="skeleton h-16 rounded-lg" />
      <div className="skeleton h-96 rounded-lg" />
    </div>
  );
}
