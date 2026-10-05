export interface BalanceHistoryPoint {
  date: string;
  won: number;
  lost: number;
  net: number;
  balance: number;
  pending: number;
}

export interface BalanceHistorySeries {
  customer_id: string;
  label: string;
  color: string;
  points: BalanceHistoryPoint[];
}

/** Build the combined account series rendered by the total-balance chart. */
export function buildTotalHistory(
  accountSeries: BalanceHistorySeries[],
): BalanceHistorySeries {
  const totalsByDate = new Map<string, BalanceHistoryPoint>();

  for (const series of accountSeries) {
    for (const point of series.points) {
      const total = totalsByDate.get(point.date) ?? {
        date: point.date,
        won: 0,
        lost: 0,
        net: 0,
        balance: 0,
        pending: 0,
      };
      total.net += point.net;
      total.balance += point.balance;
      total.pending += point.pending;
      totalsByDate.set(point.date, total);
    }
  }

  const points = [...totalsByDate.values()].sort((a, b) =>
    a.date.localeCompare(b.date),
  );

  return {
    customer_id: "__total__",
    label: "All accounts",
    color: "var(--color-accent)",
    points,
  };
}
