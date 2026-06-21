"use client";

import { useState } from "react";
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
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="rounded border border-border-subtle bg-bg-1 hover:bg-bg-2 px-3 py-1.5 text-sm"
      >
        Import CSV ▾
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-80 rounded border border-border-subtle bg-bg-1 shadow-lg p-3 z-10">
          <p className="text-xs text-text-2 mb-2">
            Upload a CSV of bets from any book. Coral33/Kalshi/Polymarket sync
            automatically — use this for everything else.
          </p>
          <a
            href={`${BASE}/api/bets/import/template`}
            className="text-xs text-accent underline mb-2 inline-block"
          >
            Download template
          </a>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={handleFile}
            disabled={busy}
            className="block w-full text-xs"
          />
          {busy && <p className="text-xs text-text-3 mt-2">Uploading…</p>}
          {result && (
            <div className="mt-3 text-xs">
              <p className="text-price-up">Accepted: {result.accepted}</p>
              {result.rejected.length > 0 && (
                <>
                  <p className="text-price-down mt-1">
                    Rejected: {result.rejected.length}
                  </p>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-auto">
                    {result.rejected.map((e, i) => (
                      <li key={i} className="text-text-3">
                        Row {e.row}: {e.reason}
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
