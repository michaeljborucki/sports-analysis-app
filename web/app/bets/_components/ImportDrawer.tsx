"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Download, Upload } from "lucide-react";
import { useSWRConfig } from "swr";
import { BASE } from "@/lib/api";

interface ImportResult {
  accepted: number;
  rejected: { row: number; reason: string }[];
}

export function ImportDrawer() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const { mutate } = useSWRConfig();
  const rootRef = useRef<HTMLDivElement>(null);

  // Dismiss on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await fetch(`${BASE}/api/bets/import`, {
        method: "POST",
        body: form,
      });
      const body: ImportResult = await r.json();
      setResult(body);
      // Refresh the bets table + rollups
      mutate((k) => typeof k === "string" && k.includes("/api/bets"));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={clsx(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-[length:var(--fs-13)] font-medium",
          "border border-border-subtle transition-colors",
          open ? "bg-bg-2 text-text-1" : "bg-bg-1 text-text-2 hover:text-text-1 hover:bg-bg-2",
        )}
      >
        <Upload size={13} aria-hidden />
        Import CSV
        <ChevronDown size={12} aria-hidden className={clsx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Import bets from CSV"
          className="absolute right-0 z-20 mt-1.5 w-80 rounded-lg border border-border-subtle bg-bg-1 p-4 shadow-[0_8px_24px_rgb(0_0_0/0.35)] flex flex-col gap-3"
        >
          <p className="text-[length:var(--fs-13)] leading-[var(--lh-13)] text-text-2">
            Upload a CSV of bets from any book. Coral33, Kalshi and Polymarket sync
            automatically, so use this for everything else.
          </p>
          <a
            href={`${BASE}/api/bets/import/template`}
            className="inline-flex w-fit items-center gap-1.5 text-[length:var(--fs-13)] font-medium text-text-1 underline-offset-2 hover:underline"
          >
            <Download size={12} aria-hidden />
            Download template
          </a>
          <label
            className={clsx(
              "flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border-subtle bg-bg-0 px-3 py-4 text-center",
              "text-[length:var(--fs-13)] text-text-2 transition-colors",
              busy ? "cursor-wait opacity-70" : "cursor-pointer hover:bg-bg-2 hover:text-text-1",
            )}
          >
            <span className="font-medium">{busy ? "Uploading…" : "Choose a CSV file"}</span>
            <span className="text-[length:var(--fs-11)] text-text-3">.csv only</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={handleFile}
              disabled={busy}
              className="sr-only"
            />
          </label>
          {result && (
            <div className="flex flex-col gap-1 text-[length:var(--fs-13)]">
              <p className="text-text-2">
                Accepted <span className="tabular text-text-1">{result.accepted}</span>
              </p>
              {result.rejected.length > 0 && (
                <>
                  <p className="text-stale">
                    Rejected <span className="tabular">{result.rejected.length}</span>
                  </p>
                  <ul className="max-h-32 overflow-auto space-y-0.5 text-[length:var(--fs-12)] text-text-3">
                    {result.rejected.map((e, i) => (
                      <li key={i}>
                        Row <span className="tabular">{e.row}</span>: {e.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
