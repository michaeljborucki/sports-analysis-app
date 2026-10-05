"use client";

import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import clsx from "clsx";

import { Chip, ErrorBanner, Panel, StatTile, type ChipTone } from "@/components/ui";
import { useIsMounted } from "@/lib/use-is-mounted";
import {
  conflictingWagers,
  contextWarningTitle,
  formatAmerican,
  groupEvaluations,
  statusLabel,
  type SystemEvaluation,
  type SystemsResponse,
  type SystemsTimeframe,
  type SystemStatus,
} from "@/lib/systems";

const STATUS_TONE: Record<SystemStatus, ChipTone> = {
  qualified: "edge",
  no_match: "neutral",
  no_slate: "neutral",
  unable_to_evaluate: "stale",
  disabled: "neutral",
};

function StatusChip({ status, timeframe }: { status: SystemStatus; timeframe: SystemsTimeframe }) {
  return (
    <Chip tone={STATUS_TONE[status]} className={clsx(status === "disabled" && "opacity-60")}>
      {statusLabel(status, timeframe)}
    </Chip>
  );
}

function EvaluationRow({ evaluation, timeframe }: { evaluation: SystemEvaluation; timeframe: SystemsTimeframe }) {
  const muted = evaluation.status === "disabled" || evaluation.status === "no_slate";
  return (
    <tr className="dt-row last:border-b-0">
      <td className="dt-td w-[48px] align-top">
        <span className="tabular text-[length:var(--fs-12)] text-text-3">{evaluation.short_id}</span>
      </td>
      <td className="dt-td align-top">
        <div className={clsx("font-medium", muted ? "text-text-2" : "text-text-1")}>{evaluation.system_name}</div>
        <div className="mt-0.5 text-[length:var(--fs-12)] text-text-3">
          {evaluation.bet_type}. Source claim: {evaluation.source_claim}
          {evaluation.rule_status === "requires_verification" && (
            <span className="text-stale"> Rule not yet verified.</span>
          )}
        </div>
        <EvaluationNote evaluation={evaluation} />
      </td>
      <td className="dt-td w-0 whitespace-nowrap text-right align-top">
        <StatusChip status={evaluation.status} timeframe={timeframe} />
      </td>
    </tr>
  );
}

function EvaluationNote({ evaluation }: { evaluation: SystemEvaluation }) {
  const plural = (n: number, w: string) => `${w}${n === 1 ? "" : w.endsWith("ch") ? "es" : "s"}`;
  return (
    <div className="mt-0.5 text-[length:var(--fs-12)] text-text-2">
      {evaluation.match_count > 0 && (
        <span>
          <span className="tabular">{evaluation.match_count}</span> {plural(evaluation.match_count, "match")}
        </span>
      )}
      {evaluation.status === "disabled" && "Source rule is incomplete, so detection is intentionally off."}
      {evaluation.status === "no_match" && (
        <span>
          Judged <span className="tabular">{evaluation.evaluated_games}</span> {plural(evaluation.evaluated_games, "game")}; none met the rule.
        </span>
      )}
      {evaluation.skipped_games > 0 && (
        <span className="block text-stale">
          <span className="tabular">{evaluation.skipped_games}</span> {plural(evaluation.skipped_games, "game")} skipped, missing{" "}
          {evaluation.missing_fields.map(field => field.replaceAll("_", " ")).join(", ")}
        </span>
      )}
    </div>
  );
}

export function SystemsWorkbench({ data, timeframe }: { data: SystemsResponse; timeframe: SystemsTimeframe }) {
  const mounted = useIsMounted();
  const [hideConflicts, setHideConflicts] = useState(true);
  const conflicts = useMemo(() => conflictingWagers(data.wagers), [data.wagers]);
  const visibleWagers = hideConflicts ? data.wagers.filter(wager => !conflicts.has(wager)) : data.wagers;
  const groups = groupEvaluations(data.evaluations);
  const timeframeLabel = timeframe === "today" ? "today" : timeframe === "tomorrow" ? "tomorrow" : "upcoming";
  const timeFormat = new Intl.DateTimeFormat(
    undefined,
    timeframe === "upcoming"
      ? { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
      : { hour: "numeric", minute: "2-digit" },
  );

  return (
    <div className="flex min-w-0 flex-col gap-5">
      {data.context_warnings.length > 0 && (
        <ErrorBanner
          title={contextWarningTitle(data.context_warnings, data.summary.unable_to_evaluate)}
          details={data.context_warnings.join("\n\n")}
        />
      )}

      <section aria-label="Systems summary" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label={hideConflicts && conflicts.size > 0 ? "Visible qualifying wagers" : "Qualifying wagers"}
          value={visibleWagers.length}
          tone="edge"
        />
        <StatTile label="Qualifying systems" value={data.summary.qualifying_systems} tone="edge" />
        <StatTile label={statusLabel("no_match", timeframe)} value={data.summary.no_match} />
        <StatTile label="Out of season" value={data.summary.no_slate} />
        <StatTile
          label="Unable to evaluate"
          value={data.summary.unable_to_evaluate}
          tone={data.summary.unable_to_evaluate > 0 ? "stale" : undefined}
        />
        <StatTile label="Disabled rules" value={data.summary.disabled} />
      </section>

      <Panel
        title={`${timeframe === "upcoming" ? "Upcoming" : timeframe === "tomorrow" ? "Tomorrow’s" : "Today’s"} qualifying wagers`}
        actions={
          <>
            <span role="status" className="hidden text-[length:var(--fs-12)] text-text-3 md:inline">
              {conflicts.size > 0
                ? `${conflicts.size} conflicting picks ${hideConflicts ? "hidden" : "shown"}`
                : "No conflicting picks"}
            </span>
            <label className="inline-flex cursor-pointer items-center gap-2 text-[length:var(--fs-13)] text-text-2">
              <input
                type="checkbox"
                checked={hideConflicts}
                onChange={event => setHideConflicts(event.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-text-1)]"
              />
              Hide conflicting picks
            </label>
          </>
        }
        bodyClassName="overflow-x-auto"
      >
        {visibleWagers.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <p className="text-[length:var(--fs-14)] font-medium text-text-1">
              {data.wagers.length > 0 ? "All qualifying picks have conflicting signals" : `No qualifying ${timeframeLabel} wagers`}
            </p>
            <p className="mx-auto mt-1 max-w-xl text-[length:var(--fs-13)] text-text-3">
              {data.wagers.length > 0
                ? "Turn off “Hide conflicting picks” to review both sides and each system’s reasoning."
                : "The audit below separates a true no-match from systems blocked by missing context."}
            </p>
          </div>
        ) : (
          <table className="w-full min-w-[820px] border-collapse">
            <thead className="dt-head">
              <tr>
                <th className="dt-th w-[120px]">Starts</th>
                <th className="dt-th">Matchup</th>
                <th className="dt-th">Wager</th>
                <th className="dt-th w-[120px]">Line</th>
                <th className="dt-th">Why</th>
              </tr>
            </thead>
            <tbody>
              {visibleWagers.map(wager => (
                <tr key={`${wager.event_id}-${wager.bet_type}-${wager.selection}`} className="dt-row last:border-b-0">
                  <td className="dt-td align-top whitespace-nowrap">
                    <span className="tabular text-text-2">{mounted ? timeFormat.format(new Date(wager.commence_time)) : null}</span>
                  </td>
                  <td className="dt-td align-top text-text-1">
                    {wager.away_team} <span className="text-text-3">at</span> {wager.home_team}
                  </td>
                  <td className="dt-td align-top">
                    <div className="font-medium text-text-1">{wager.selection}</div>
                    {conflicts.has(wager) && (
                      <span className="mt-1 inline-flex items-center gap-1 text-[length:var(--fs-12)] text-stale">
                        <AlertTriangle size={12} aria-hidden />
                        Conflicting systems
                      </span>
                    )}
                    <div className="mt-1 flex flex-wrap gap-1">
                      {wager.supporting_system_names.map(name => (
                        <Chip key={name}>{name}</Chip>
                      ))}
                    </div>
                  </td>
                  <td className="dt-td align-top">
                    <span className={clsx("tabular font-semibold", wager.price_american == null ? "text-text-3" : "text-text-1")}>
                      {formatAmerican(wager.price_american)}
                    </span>
                    <span className="block text-[length:var(--fs-12)] text-text-3">{wager.book ?? "Not at Coral33"}</span>
                  </td>
                  <td className="dt-td align-top text-[length:var(--fs-12)] text-text-2">{wager.qualification_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <section>
        <div className="mb-3">
          <h2 className="text-[length:var(--fs-16)] leading-[var(--lh-16)] font-semibold text-text-1">
            All <span className="tabular">{data.evaluations.length}</span> systems
          </h2>
          <p className="mt-0.5 text-[length:var(--fs-12)] text-text-3">
            Football 2B is tracked as a nested subset signal beneath Football 2.
          </p>
        </div>
        <div className="grid min-w-0 items-start gap-4 xl:grid-cols-2">
          {Object.entries(groups).map(([label, evaluations]) => (
            <Panel
              key={label}
              title={label}
              actions={
                <span className="text-[length:var(--fs-12)] text-text-3">
                  <span className="tabular">{evaluations.length}</span> systems
                </span>
              }
              className={clsx("min-w-0", label === "MLB" && "xl:row-span-2")}
            >
              <table className="w-full border-collapse">
                <tbody>
                  {evaluations.map(evaluation => (
                    <EvaluationRow key={evaluation.system_id} evaluation={evaluation} timeframe={timeframe} />
                  ))}
                </tbody>
              </table>
            </Panel>
          ))}
        </div>
      </section>
    </div>
  );
}
