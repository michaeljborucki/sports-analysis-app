"use client";
import type { ReactNode } from "react";
import clsx from "clsx";


/**
 * Teaching empty state for data surfaces.
 *
 * Use when a panel/table has legitimately zero rows and the user needs to
 * know *why* — distinct from a loading skeleton (data incoming) and from an
 * error banner (fetch failed). Sized for in-table drop-in; the container
 * renders a bordered `bg-1` card so it reads as "working, but empty" rather
 * than "broken" on a void background.
 *
 * Copy guidance (caller's job, not this component's):
 * - `title`: diagnose the cause in ~60 chars. "No X right now — cache is Ym old."
 * - `body`: one or two sentences, ~200 chars. Ground it in mechanics
 *   (cache age, filter interaction, missing books).
 * - `hints`: optional cause taxonomy — power-user voice. Each `label` is a
 *   short cause tag (e.g. "Cache stale"), each `hint` is the one-line
 *   explanation. Rendered as a bulleted list.
 * - `action`: the single most useful CTA. Reuses the Settings "Save changes"
 *   primary-button treatment for visual consistency.
 * - `tone="warning"`: tints the border with the `stale` role, used when the
 *   empty state is caused by stale data (fetchers off, old cache).
 */
export interface EmptyStateProps {
  title: string;
  body?: string;
  icon?: ReactNode;
  hints?: Array<{ label: string; hint: string }>;
  action?: {
    label: string;
    onClick: () => void;
    variant?: "primary" | "ghost";
  };
  tone?: "neutral" | "warning";
}


export function EmptyState({
  title,
  body,
  icon,
  hints,
  action,
  tone = "neutral",
}: EmptyStateProps) {
  const actionVariant = action?.variant ?? "primary";
  return (
    <div
      className={clsx(
        "mx-auto flex max-w-[480px] flex-col items-center gap-3 rounded-lg border bg-bg-1 px-6 py-10 text-center",
        tone === "warning"
          ? "border-[var(--stale-25)]"
          : "border-border-subtle"
      )}
      role="status"
      aria-live="polite"
    >
      {icon && (
        <div
          className={clsx(
            "flex h-7 w-7 items-center justify-center",
            tone === "warning" ? "text-stale" : "text-text-3"
          )}
          aria-hidden="true"
        >
          {icon}
        </div>
      )}

      <h3 className="text-[length:var(--fs-16)] leading-[var(--lh-16)] font-semibold text-text-1">
        {title}
      </h3>

      {body && (
        <p className="text-[length:var(--fs-13)] leading-[var(--lh-13)] text-text-2">
          {body}
        </p>
      )}

      {hints && hints.length > 0 && (
        <ul className="mt-1 flex w-full flex-col gap-1.5 text-left text-[length:var(--fs-12)] leading-[var(--lh-12)] text-text-2">
          {hints.map((h, i) => (
            <li key={i} className="flex gap-2">
              <span
                className="mt-[5px] inline-block h-1 w-1 flex-shrink-0 rounded-full bg-text-3"
                aria-hidden="true"
              />
              <span>
                <span className="font-medium text-text-1">{h.label}.</span>{" "}
                <span>{h.hint}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {action && (
        <button
          onClick={action.onClick}
          className={clsx(
            "mt-2 h-8 rounded-md px-4 text-[length:var(--fs-13)] font-medium transition-colors",
            actionVariant === "primary"
              ? "bg-text-1 text-bg-0 hover:bg-text-2"
              : "border border-border-subtle bg-bg-1 text-text-2 hover:bg-bg-2 hover:text-text-1"
          )}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
