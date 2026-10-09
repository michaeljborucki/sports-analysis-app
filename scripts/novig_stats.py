"""Novig trading-subaccount stats — totals and per-day.

    python3 scripts/novig_stats.py            # report
    python3 scripts/novig_stats.py --json     # machine-readable
    python3 scripts/novig_stats.py --days 7   # daily table length

READ-ONLY: signed GETs against the trading subaccount (fills, positions,
ledger, open orders, balance) plus the auto-maker's own event log to tell EV
orders from hedge orders. Never places or cancels anything.

Novig contracts pay $0.01; fill `cost` is dollars. Each binary market nets as:
  matched  = min(qty side A, qty side B)   -> locked: matched*0.01 - pair cost
  unmatched = the excess on the bigger side -> still at risk (its cost)
A market missing from /portfolio/positions is closed: profit = SETTLEMENT
cash (ref = marketId) - every fill cost in it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "logs" / "novig_automaker.jsonl"
TZ = ZoneInfo("America/Denver")
PAYOUT = 0.01


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d")


def _maker_log() -> tuple[set[str], dict[str, dict], dict[str, float], dict[str, str]]:
    """Hedge order ids, outcome -> description, outcome -> latest fair,
    hedge order id -> the position outcome it hedges."""
    hedge_ids: set[str] = set()
    hedge_for: dict[str, str] = {}
    desc: dict[str, dict] = {}
    fair: dict[str, float] = {}
    if not LOG_PATH.exists():
        return hedge_ids, desc, fair, hedge_for
    with LOG_PATH.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            act = r.get("action")
            if act == "hedge_place" and r.get("order_id"):
                hedge_ids.add(r["order_id"])
                hedge_for[r["order_id"]] = r.get("position_outcome_id")
            if act in ("place", "hedge_place") and r.get("outcome_id"):
                desc[r["outcome_id"]] = {k: r.get(k) for k in (
                    "sport_key", "away_team", "home_team", "market_key", "outcome_name", "point")}
                if r.get("fair") is not None and r.get("mode") == "live":
                    fair[r["outcome_id"]] = float(r["fair"])
            if act == "fill_event" and r.get("hedge") and r.get("order_id"):
                hedge_ids.add(r["order_id"])
    return hedge_ids, desc, fair, hedge_for


def _label(d: dict | None) -> str:
    if not d:
        return "?"
    p = d.get("point")
    pt = (f" {p:+g}" if d.get("market_key") == "spreads" else f" {p:g}") if isinstance(p, (int, float)) else ""
    return (f"{d.get('sport_key')}: {d.get('away_team')} @ {d.get('home_team')} | "
            f"{d.get('market_key')} {d.get('outcome_name')}{pt}")


async def _fetch() -> dict:
    from server.odds.books.novig.trading import NovigTrader
    t = NovigTrader()
    try:
        fills, after = [], 0
        while True:
            page = await t.fills_since(after)
            new = [f for f in page if f["fillId"] not in {x["fillId"] for x in fills}]
            fills.extend(new)
            if len(page) < 500 or not new:
                break
            after = max(int(f["ts"]) for f in page)
        txs, cursor = [], None
        while True:
            params = {"limit": 5000}
            if cursor:
                params["after"] = cursor
            page = await t._call("GET", f"/v3/account/subaccounts/{t.key_id}/transactions", params)
            txs.extend(page.get("items") or [])
            cursor = page.get("next")
            if not cursor:
                break
        return {
            "fills": fills, "txs": txs,
            "positions": await t.positions(),
            "open_orders": await t.open_orders(),
            "cash": await t.balance(),
        }
    finally:
        await t.aclose()


def compute(raw: dict, days: int) -> dict:
    hedge_ids, desc, fair, hedge_for = _maker_log()
    fills, txs = raw["fills"], raw["txs"]

    # ── fills: EV vs hedge ──
    def kind(f):
        return "hedge" if f["orderId"] in hedge_ids else "ev"

    def agg(rows):
        return {"n": len(rows), "contracts": sum(int(f["qty"]) for f in rows),
                "staked": round(sum(float(f["cost"]) for f in rows), 2),
                "as_taker": sum(1 for f in rows if f.get("taker")),
                "orders": len({f["orderId"] for f in rows})}

    ev_fills = [f for f in fills if kind(f) == "ev"]
    hedge_fills = [f for f in fills if kind(f) == "hedge"]

    # ── per market from fills ──
    mk: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"qty": 0, "cost": 0.0}))
    for f in fills:
        s = mk[f["marketId"]][f["outcomeId"]]
        s["qty"] += int(f["qty"])
        s["cost"] += float(f["cost"])
    open_markets = {p["marketId"] for p in raw["positions"] if int(p.get("qty") or 0) > 0}
    settle_by_mkt: dict[str, float] = defaultdict(float)
    settle_ts: dict[str, int] = {}
    for x in txs:
        if x["kind"] == "SETTLEMENT":
            settle_by_mkt[x["ref"]] += float(x["amount"])
            settle_ts[x["ref"]] = max(settle_ts.get(x["ref"], 0), int(x["ts"]))

    closed, open_rows = [], []
    for mid, sides in mk.items():
        cost_all = sum(s["cost"] for s in sides.values())
        if mid not in open_markets:
            paid = settle_by_mkt.get(mid, 0.0)
            oid = next(iter(sides))
            closed.append({"market_id": mid, "label": _label(desc.get(oid)),
                           "cost": round(cost_all, 2), "paid": round(paid, 2),
                           "profit": round(paid - cost_all, 2),
                           "day": _day(settle_ts[mid]) if mid in settle_ts else None,
                           "hedged": len(sides) == 2})
            continue
        ss = sorted(sides.items(), key=lambda kv: -kv[1]["qty"])
        (big_id, big), rest = ss[0], ss[1:]
        small_qty = rest[0][1]["qty"] if rest else 0
        small_avg = rest[0][1]["cost"] / small_qty if small_qty else 0.0
        big_avg = big["cost"] / big["qty"]
        matched = small_qty if len(ss) == 2 else 0
        locked = matched * PAYOUT - matched * (big_avg + small_avg)
        unq = big["qty"] - matched
        at_risk = unq * big_avg
        p = fair.get(big_id)
        hedge_out = [o for o in raw["open_orders"] if hedge_for.get(o["orderId"]) == big_id]
        open_rows.append({
            "market_id": mid, "outcome_id": big_id, "label": _label(desc.get(big_id)),
            "matched_qty": matched, "locked_profit": round(locked, 2),
            "unhedged_qty": unq, "avg_price": round(big_avg / PAYOUT, 4),
            "at_risk": round(at_risk, 2),
            "win_if_hits": round(unq * PAYOUT - at_risk, 2),
            "ev_dollars": round(unq * PAYOUT * p - at_risk, 2) if p is not None else None,
            "hedge_resting": [{"price": o.get("price"), "qty": o.get("qty")} for o in hedge_out],
        })

    unhedged = sorted([r for r in open_rows if r["unhedged_qty"] > 0], key=lambda r: -r["at_risk"])

    # ── ledger totals ──
    led: dict[str, float] = defaultdict(float)
    for x in txs:
        led[x["kind"]] += float(x["amount"])
    deposits = led.get("TRANSFER_IN", 0.0) + led.get("TRANSFER_OUT", 0.0) + led.get("DEPOSIT", 0.0) + led.get("WITHDRAWAL", 0.0)
    cash = raw["cash"]
    at_risk_total = round(sum(r["at_risk"] for r in unhedged), 2)
    equity_at_cost = cash + at_risk_total
    closed_profit = round(sum(c["profit"] for c in closed), 2)
    locked_total = round(sum(r["locked_profit"] for r in open_rows), 2)
    credits = round(led.get("MAKER_CREDIT", 0.0), 2)

    # ── daily ──
    daily: dict[str, dict] = defaultdict(lambda: {"ev_fills": 0, "ev_staked": 0.0, "hedge_fills": 0,
                                                  "hedge_staked": 0.0, "settled_cash": 0.0,
                                                  "closed_profit": 0.0, "markets_closed": 0,
                                                  "maker_credits": 0.0})
    for f in fills:
        d = daily[_day(int(f["ts"]))]
        k = kind(f)
        d[f"{k}_fills"] += 1
        d[f"{k}_staked"] += float(f["cost"])
    for x in txs:
        if x["kind"] == "SETTLEMENT":
            daily[_day(int(x["ts"]))]["settled_cash"] += float(x["amount"])
        if x["kind"] == "MAKER_CREDIT":
            daily[_day(int(x["ts"]))]["maker_credits"] += float(x["amount"])
    for c in closed:
        if c["day"]:
            daily[c["day"]]["closed_profit"] += c["profit"]
            daily[c["day"]]["markets_closed"] += 1
    daily_rows = [{"day": k, **{kk: round(v, 2) if isinstance(v, float) else v for kk, v in d.items()}}
                  for k, d in sorted(daily.items())][-days:]

    return {
        "as_of": datetime.now(TZ).isoformat(timespec="seconds"),
        "totals": {
            "deposited": round(deposits, 2),
            "cash": round(cash, 2),
            "at_risk_unhedged": at_risk_total,
            "equity_at_cost": round(equity_at_cost, 2),
            "pnl_at_cost": round(equity_at_cost - deposits, 2),
            "closed_profit": closed_profit,
            "locked_profit_open_markets": locked_total,
            "maker_credits": credits,
            "fees": round(led.get("FEE", 0.0), 2),
            "unexplained": round(equity_at_cost - deposits - closed_profit - locked_total - credits, 2),
            "ev_dollars_open": round(sum(r["ev_dollars"] or 0 for r in unhedged), 2),
        },
        "fills": {"all": agg(fills), "ev": agg(ev_fills), "hedge": agg(hedge_fills)},
        "markets": {
            "traded": len(mk), "closed": len(closed), "open": len(open_rows),
            "open_fully_hedged": sum(1 for r in open_rows if r["unhedged_qty"] == 0),
            "open_partly_hedged": sum(1 for r in open_rows if r["unhedged_qty"] > 0 and r["matched_qty"] > 0),
            "open_not_hedged": sum(1 for r in open_rows if r["matched_qty"] == 0),
            "unhedged_with_hedge_resting": sum(1 for r in unhedged if r["hedge_resting"]),
        },
        "open_orders": {"n": len(raw["open_orders"]),
                        "hedge": sum(1 for o in raw["open_orders"] if o["orderId"] in hedge_ids)},
        "daily": daily_rows,
        "not_hedged": unhedged,
        "closed_markets": sorted(closed, key=lambda c: c["day"] or "", reverse=True),
    }


def _print(r: dict, top: int) -> None:
    t, f, m = r["totals"], r["fills"], r["markets"]
    print(f"Novig trading subaccount — {r['as_of']}\n")
    print(f"Deposited         ${t['deposited']:>10,.2f}")
    print(f"Cash              ${t['cash']:>10,.2f}")
    print(f"At risk (unhedged)${t['at_risk_unhedged']:>10,.2f}   EV of it ${t['ev_dollars_open']:,.2f}")
    print(f"Equity at cost    ${t['equity_at_cost']:>10,.2f}   P&L at cost ${t['pnl_at_cost']:+,.2f}")
    print(f"  closed profit   ${t['closed_profit']:>+10,.2f}")
    print(f"  locked (open)   ${t['locked_profit_open_markets']:>+10,.2f}   matched pairs in markets not yet settled")
    print(f"  maker credits   ${t['maker_credits']:>+10,.2f}   fees ${t['fees']:,.2f}   unexplained ${t['unexplained']:+,.2f}\n")
    for k in ("ev", "hedge", "all"):
        a = f[k]
        print(f"{k.upper():>5} fills: {a['n']:>4}  orders {a['orders']:>4}  contracts {a['contracts']:>9,}  "
              f"staked ${a['staked']:>9,.2f}  taker {a['as_taker']}")
    print(f"\nMarkets: {m['traded']} traded · {m['closed']} closed · {m['open']} open "
          f"({m['open_fully_hedged']} fully hedged, {m['open_partly_hedged']} partly, {m['open_not_hedged']} not hedged; "
          f"{m['unhedged_with_hedge_resting']} with a hedge order resting)")
    print(f"Open orders: {r['open_orders']['n']} ({r['open_orders']['hedge']} hedges)\n")
    print("Daily (Mountain)   EV fills   EV $     hedge fills hedge $  settled $  closed P&L  mkts  credits")
    for d in r["daily"]:
        print(f"{d['day']}   {d['ev_fills']:>8} {d['ev_staked']:>9,.2f} {d['hedge_fills']:>11} {d['hedge_staked']:>8,.2f} "
              f"{d['settled_cash']:>10,.2f} {d['closed_profit']:>+11,.2f} {d['markets_closed']:>5} {d['maker_credits']:>8,.2f}")
    print(f"\nNot hedged yet (top {top} of {len(r['not_hedged'])} by $ at risk):")
    for x in r["not_hedged"][:top]:
        h = f"hedge resting @{x['hedge_resting'][0]['price']}" if x["hedge_resting"] else "no hedge resting"
        ev = f"EV ${x['ev_dollars']:+.2f}" if x["ev_dollars"] is not None else "EV ?"
        print(f"  ${x['at_risk']:>7,.2f} risk  {x['unhedged_qty']:>6} @{x['avg_price']:.3f}  win ${x['win_if_hits']:>7,.2f}  "
              f"{ev:<11} {h:<22} {x['label']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    r = compute(asyncio.run(_fetch()), a.days)
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        _print(r, a.top)


if __name__ == "__main__":
    main()
