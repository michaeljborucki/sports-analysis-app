"use client";

import { AlertTriangle, CalendarOff, Check, CircleOff, Clock3, DatabaseZap } from "lucide-react";
import clsx from "clsx";

import {
  formatAmerican,
  groupEvaluations,
  statusLabel,
  type SystemEvaluation,
  type SystemsResponse,
  type SystemsTimeframe,
  type SystemStatus,
} from "@/lib/systems";

const STATUS_STYLE: Record<SystemStatus, string> = {
  qualified: "border-price-up/40 bg-price-up/10 text-price-up",
  no_match: "border-border-subtle bg-bg-1 text-text-2",
  no_slate: "border-border-subtle bg-bg-1 text-text-3",
  unable_to_evaluate: "border-flash/40 bg-flash/10 text-flash",
  disabled: "border-border-subtle bg-bg-0 text-text-3",
};

const STATUS_ICON = {
  qualified: Check,
  no_match: CircleOff,
  no_slate: CalendarOff,
  unable_to_evaluate: AlertTriangle,
  disabled: DatabaseZap,
};

function StatusBadge({ status, timeframe }: { status: SystemStatus; timeframe: SystemsTimeframe }) {
  const Icon = STATUS_ICON[status];
  return (
    <span className={clsx("inline-flex min-h-7 items-center gap-1.5 whitespace-nowrap rounded border px-2 text-[11px] font-medium", STATUS_STYLE[status])}>
      <Icon size={12} aria-hidden />
      {statusLabel(status, timeframe)}
    </span>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="min-w-0 border-r border-border-subtle px-3 py-3 last:border-r-0">
      <div className={clsx("tabular text-xl font-semibold", tone ?? "text-text-1")}>{value}</div>
      <div className="mt-0.5 text-[11px] leading-4 text-text-3">{label}</div>
    </div>
  );
}

function EvaluationRow({ evaluation, timeframe }: { evaluation: SystemEvaluation; timeframe: SystemsTimeframe }) {
  return (
    <li className="grid min-w-0 gap-3 border-t border-border-subtle px-3 py-3 first:border-t-0 md:grid-cols-[minmax(230px,1.2fr)_auto_minmax(180px,0.8fr)] md:items-center">
      <div className="min-w-0">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="tabular shrink-0 text-[11px] font-semibold text-text-3">{evaluation.short_id}</span>
          <h3 className="min-w-0 text-sm font-medium text-text-1">{evaluation.system_name}</h3>
        </div>
        <div className="mt-1 text-[11px] leading-4 text-text-3">
          {evaluation.bet_type} · source claim: {evaluation.source_claim}
        </div>
      </div>
      <StatusBadge status={evaluation.status} timeframe={timeframe} />
      <div className="min-w-0 text-[11px] leading-4 text-text-2 md:text-right">
        {evaluation.match_count > 0 && `${evaluation.match_count} match${evaluation.match_count === 1 ? "" : "es"}`}
        {evaluation.status === "disabled" && "Source rule is incomplete; detection is intentionally off."}
        {evaluation.status === "no_slate" && "No games on this slate."}
        {evaluation.status === "no_match" && `Judged ${evaluation.evaluated_games} game${evaluation.evaluated_games === 1 ? "" : "s"}; none met the rule.`}
        {evaluation.skipped_games > 0 && (
          <span className="block text-flash">
            {evaluation.skipped_games} game{evaluation.skipped_games === 1 ? "" : "s"} skipped — missing {evaluation.missing_fields.map(field => field.replaceAll("_", " ")).join(", ")}
          </span>
        )}
      </div>
    </li>
  );
}

export function SystemsWorkbench({ data, timeframe }: { data: SystemsResponse; timeframe: SystemsTimeframe }) {
  const groups = groupEvaluations(data.evaluations);
  const timeframeLabel = timeframe === "today" ? "today" : timeframe === "tomorrow" ? "tomorrow" : "upcoming";
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <section aria-label="Systems summary" className="grid overflow-hidden rounded-md border border-border-subtle bg-bg-1 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="qualifying wagers" value={data.summary.qualifying_wagers} tone="text-price-up" />
        <Stat label="qualifying systems" value={data.summary.qualifying_systems} tone="text-price-up" />
        <Stat label={statusLabel("no_match", timeframe).toLowerCase()} value={data.summary.no_match} />
        <Stat label="out of season" value={data.summary.no_slate} />
        <Stat label="unable to evaluate" value={data.summary.unable_to_evaluate} tone="text-flash" />
        <Stat label="disabled rules" value={data.summary.disabled} />
      </section>

      {data.context_warnings.length > 0 && (
        <aside className="rounded-md border border-flash/40 bg-flash/10 px-3 py-2 text-xs leading-5 text-flash">
          {data.context_warnings.join(" · ")}
        </aside>
      )}

      <section className="min-w-0">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-text-1">{timeframe === "upcoming" ? "Upcoming" : timeframe === "tomorrow" ? "Tomorrow’s" : "Today’s"} qualifying wagers</h2>
          <span className="text-[11px] text-text-3">one row per deduplicated wager</span>
        </div>
        {data.wagers.length === 0 ? (
          <div className="rounded-md border border-border-subtle bg-bg-1 px-4 py-10 text-center">
            <Clock3 className="mx-auto mb-3 text-text-3" size={20} aria-hidden />
            <p className="text-sm font-medium text-text-1">No qualifying {timeframeLabel} wagers</p>
            <p className="mx-auto mt-1 max-w-xl text-xs leading-5 text-text-3">The audit below distinguishes a true no-match from systems blocked by missing context.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border border-border-subtle bg-bg-1">
            <div className="hidden grid-cols-[110px_minmax(180px,1fr)_minmax(160px,0.8fr)_110px_minmax(220px,1.2fr)] gap-3 bg-bg-2 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-text-3 md:grid">
              <span>Starts</span><span>Matchup</span><span>Wager</span><span>Line</span><span>Why</span>
            </div>
            <ul>
              {data.wagers.map(wager => (
                <li key={`${wager.event_id}-${wager.bet_type}-${wager.selection}`} className="grid gap-3 border-t border-border-subtle px-3 py-3 first:border-t-0 md:grid-cols-[110px_minmax(180px,1fr)_minmax(160px,0.8fr)_110px_minmax(220px,1.2fr)] md:items-center">
                  <div className="tabular text-xs text-text-2">{new Intl.DateTimeFormat(undefined, timeframe === "upcoming" ? { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" } : { hour: "numeric", minute: "2-digit" }).format(new Date(wager.commence_time))}</div>
                  <div className="min-w-0 text-sm text-text-1">{wager.away_team} <span className="text-text-3">at</span> {wager.home_team}</div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-text-1">{wager.selection}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {wager.supporting_system_names.map(name => <span key={name} className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] text-accent">{name}</span>)}
                    </div>
                  </div>
                  <div className={clsx("tabular text-sm font-semibold", wager.price_american == null ? "text-text-3" : "text-text-1")}>
                    {formatAmerican(wager.price_american)}
                    <span className="block text-[10px] font-normal text-text-3">{wager.book ?? "not at Coral33"}</span>
                  </div>
                  <div className="text-[11px] leading-4 text-text-2">{wager.qualification_reason}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section>
        <div className="mb-2">
          <h2 className="text-sm font-semibold text-text-1">All 25 systems</h2>
          <p className="mt-1 text-[11px] text-text-3">Football 2B is tracked as a nested subset signal beneath Football 2.</p>
        </div>
        <div className="grid min-w-0 gap-4 xl:grid-cols-2">
          {Object.entries(groups).map(([label, evaluations]) => (
            <section key={label} className={clsx("min-w-0 overflow-hidden rounded-md border border-border-subtle bg-bg-1", label === "MLB" && "xl:row-span-2")}>
              <header className="flex items-center justify-between bg-bg-2 px-3 py-2">
                <h2 className="text-xs font-semibold text-text-1">{label}</h2>
                <span className="tabular text-[10px] text-text-3">{evaluations.length} systems</span>
              </header>
              <ul>{evaluations.map(evaluation => <EvaluationRow key={evaluation.system_id} evaluation={evaluation} timeframe={timeframe} />)}</ul>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}
