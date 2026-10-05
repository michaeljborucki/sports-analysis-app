"use client";

import clsx from "clsx";
import { ChevronDown } from "lucide-react";

import { SPORTS, SPORT_ORDER } from "@/lib/sports";
import { LEDGER_BOOKS } from "./labels";

export interface BetFilters {
  book: string;
  sport: string;
  status: string;
}

const SPORT_OPTIONS = SPORT_ORDER.map(k => ({ value: k, label: SPORTS[k].label }));

const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "win", label: "Win" },
  { value: "loss", label: "Loss" },
  { value: "push", label: "Push" },
  { value: "pending", label: "Pending" },
];

function Select({
  label,
  value,
  allLabel,
  options,
  onChange,
}: {
  label: string;
  value: string;
  allLabel: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={clsx(
          "h-8 appearance-none rounded-md border border-border-subtle pl-3 pr-7",
          "text-[length:var(--fs-13)] font-medium transition-colors cursor-pointer",
          "hover:text-text-1 focus-visible:outline-none focus-visible:border-text-3",
          value ? "bg-bg-2 text-text-1" : "bg-bg-1 text-text-2",
        )}
      >
        <option value="">{allLabel}</option>
        {options.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={12}
        aria-hidden
        className="pointer-events-none absolute right-2.5 text-text-3"
      />
    </label>
  );
}

export function Filters({
  value,
  onChange,
}: {
  value: BetFilters;
  onChange: (next: BetFilters) => void;
}) {
  const active = Boolean(value.book || value.sport || value.status);
  return (
    <div className="flex flex-wrap gap-2 items-center">
      <Select
        label="Book"
        value={value.book}
        allLabel="All books"
        options={LEDGER_BOOKS}
        onChange={(book) => onChange({ ...value, book })}
      />
      <Select
        label="Sport"
        value={value.sport}
        allLabel="All sports"
        options={SPORT_OPTIONS}
        onChange={(sport) => onChange({ ...value, sport })}
      />
      <Select
        label="Status"
        value={value.status}
        allLabel="All statuses"
        options={STATUS_OPTIONS}
        onChange={(status) => onChange({ ...value, status })}
      />
      {active && (
        <button
          type="button"
          onClick={() => onChange({ book: "", sport: "", status: "" })}
          className="h-8 px-2 text-[length:var(--fs-13)] text-text-3 hover:text-text-1"
        >
          Clear
        </button>
      )}
    </div>
  );
}
