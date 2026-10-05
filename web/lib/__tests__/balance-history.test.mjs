import assert from "node:assert/strict";
import test from "node:test";

import { buildTotalHistory } from "../balance-history.ts";

test("combines unequal account histories by date instead of array index", () => {
  const total = buildTotalHistory([
    {
      customer_id: "A",
      label: "A",
      color: "cyan",
      points: [
        { date: "2026-08-18", won: 0, lost: 0, net: 10, balance: 100, pending: 10 },
        { date: "2026-08-19", won: 0, lost: 0, net: 20, balance: 120, pending: 20 },
      ],
    },
    {
      customer_id: "B",
      label: "B",
      color: "green",
      points: [
        { date: "2026-08-17", won: 0, lost: 0, net: 5, balance: 200, pending: 0 },
        { date: "2026-08-18", won: 0, lost: 0, net: 15, balance: 215, pending: 30 },
        { date: "2026-08-19", won: 0, lost: 0, net: 25, balance: 240, pending: 40 },
      ],
    },
  ]);

  assert.deepEqual(total.points, [
    { date: "2026-08-17", won: 0, lost: 0, net: 5, balance: 200, pending: 0 },
    { date: "2026-08-18", won: 0, lost: 0, net: 25, balance: 315, pending: 40 },
    { date: "2026-08-19", won: 0, lost: 0, net: 45, balance: 360, pending: 60 },
  ]);
});
