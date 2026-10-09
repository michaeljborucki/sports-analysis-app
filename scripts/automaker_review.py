"""Review pass for the live Novig auto-maker. Read-only: places nothing.

Run: .venv/bin/python scripts/automaker_review.py

Each run:
  * health: process alive, errors / fail-safes since the last pass, balance,
    open orders (signed GETs with the trading key — reads only);
  * fill quality: every fill is joined to the order we posted (price, fair
    at post time, fair source) and its fair probability is re-sampled from
    the live candidate feed on every pass, so over time each fill carries a
    fair-price path ending at game start (closing value);
  * writes a JSON summary to stdout and appends a dated section to
    docs/automaker/improvement-log.md.

State (fill fair-paths, last-run marker) lives in logs/automaker_review_state.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG = ROOT / "logs" / "novig_automaker.jsonl"
OUT = ROOT / "logs" / "novig_automaker.out"
PID = ROOT / "logs" / "novig_automaker.pid"
STATE = ROOT / "logs" / "automaker_review_state.json"
REPORT = ROOT / "docs" / "automaker" / "improvement-log.md"
FEED = "http://127.0.0.1:8000/api/novig/maker-candidates"


def _alive() -> bool:
    try:
        os.kill(int(PID.read_text().strip()), 0)
        return True
    except Exception:
        return False


def _records() -> list[dict]:
    """Log rows with `ts` normalized to an ISO string. Early fill rows carry
    Novig's millisecond `ts` (it overwrote the log timestamp); newer rows
    keep that as `fill_ts`."""
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.open():
        r = json.loads(line)
        if isinstance(r.get("ts"), (int, float)):
            r["fill_ts"] = r["ts"]
            r["ts"] = datetime.fromtimestamp(r["ts"] / 1000, timezone.utc).isoformat()
        rows.append(r)
    return rows


async def _account(since_ms: int | None) -> dict:
    """Balance, open orders, the subaccount ledger by kind (MAKER_CREDIT is
    the Maker Credit Program cash credit), and fee status of recent fills.
    All signed GETs — reads only."""
    from server.odds.books.novig.trading import NovigTrader
    t = NovigTrader()
    try:
        out = {"balance": await t.balance(), "open_orders": len(await t.open_orders())}
        txs, after = [], None
        while True:
            params = {"limit": 5000}
            if after:
                params["after"] = after
            page = await t._call("GET", f"/v3/account/subaccounts/{t.key_id}/transactions", params)
            txs.extend(page.get("items") or [])
            after = page.get("next")
            if not after:
                break

        def by_kind(rows):
            agg: dict[str, dict] = {}
            for x in rows:
                a = agg.setdefault(x["kind"], {"n": 0, "total": 0.0})
                a["n"] += 1
                a["total"] = round(a["total"] + float(x["amount"]), 5)
            return agg

        out["ledger_all"] = by_kind(txs)
        out["ledger_since_last_pass"] = by_kind(
            [x for x in txs if since_ms is None or x["ts"] > since_ms])
        mc = out["ledger_all"].get("MAKER_CREDIT", {"n": 0, "total": 0.0})
        out["maker_credits_total"] = mc["total"]

        fills = await t.fills_since(int(time.time() * 1000) - 7 * 86400_000)
        maker = [f for f in fills if not f.get("taker")]
        out["fills_7d"] = {
            "n": len(fills),
            "as_maker": len(maker),
            "as_taker": len(fills) - len(maker),
            "with_fee_charged": sum(1 for f in fills if f.get("fee")),
            "fees_total": round(sum(float(f.get("fee") or 0) for f in fills), 5),
            "maker_staked": round(sum(float(f["cost"]) for f in maker), 2),
        }
        return out
    finally:
        await t.aclose()


def main() -> None:
    now = datetime.now(timezone.utc)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"fills": {}, "last_run": None}
    since = state.get("last_run")
    recs = [r for r in _records() if r.get("mode") == "live"]
    recent = [r for r in recs if since is None or r["ts"] > since]

    # Latest placement per outcome (fills match the order we posted).
    placed: dict[str, dict] = {}
    for r in recs:
        if r["action"] == "place":
            placed[r["outcome_id"]] = r

    try:
        feed = json.load(urllib.request.urlopen(FEED, timeout=60))
        fair_now = {c["outcome_id"]: c["fair_probability"] for c in feed["candidates"]}
    except Exception as e:
        feed, fair_now = {"error": str(e)}, {}

    # Track every fill's fair path.
    for r in recs:
        if r["action"] != "fill":
            continue
        fid = r.get("fillId")
        oid = r.get("outcomeId")
        if not fid or not oid:
            continue
        f = state["fills"].get(fid)
        if f is None:
            p = placed.get(oid, {})
            qty = int(r.get("qty") or 0)
            price = float(r.get("cost") or 0) * 100.0 / qty if qty else None
            f = state["fills"][fid] = {
                "outcome_id": oid, "ts": r.get("ts"), "qty": qty,
                "cost": float(r.get("cost") or 0), "price": price,
                "fair_at_post": p.get("fair"), "ev_at_post": p.get("ev_pct"),
                "fair_source": p.get("fair_source"), "sport": p.get("sport_key"),
                "market": p.get("market_key"),
                "desc": f"{p.get('away_team')} @ {p.get('home_team')} | {p.get('market_key')} "
                        f"{p.get('outcome_name')} {p.get('point')}",
                "path": [],
            }
        if oid in fair_now:
            f["path"].append([now.isoformat(), fair_now[oid]])

    # Fill quality: value of each fill at the latest fair we saw for it.
    graded = []
    for f in state["fills"].values():
        if not f["path"] or not f["price"]:
            continue
        latest = f["path"][-1][1]
        graded.append({
            "ev_now_pct": (latest / f["price"] - 1) * 100,
            "ev_post_pct": f["ev_at_post"],
            "drift_pct_pts": (latest - (f["fair_at_post"] or latest)) * 100,
            "cost": f["cost"], "source": f["fair_source"], "market": f["market"],
        })

    def agg(rows):
        if not rows:
            return None
        w = sum(r["cost"] for r in rows) or 1
        return {
            "n": len(rows),
            "staked": round(sum(r["cost"] for r in rows), 2),
            "avg_ev_at_post_pct": round(statistics.mean(r["ev_post_pct"] or 0 for r in rows), 2),
            "avg_ev_now_pct": round(statistics.mean(r["ev_now_pct"] for r in rows), 2),
            "stake_weighted_ev_now_pct": round(sum(r["ev_now_pct"] * r["cost"] for r in rows) / w, 2),
            "avg_fair_drift_pct_pts": round(statistics.mean(r["drift_pct_pts"] for r in rows), 2),
        }

    by_source = {s: agg([g for g in graded if g["source"] == s])
                 for s in sorted({g["source"] for g in graded if g["source"]})}
    by_market = {m: agg([g for g in graded if (g["market"] or "").startswith(m)])
                 for m in ("h2h", "spreads", "totals", "player", "alternate", "team")}

    since_ms = int(datetime.fromisoformat(since).timestamp() * 1000) if since else None
    try:
        acct = asyncio.run(_account(since_ms))
    except Exception as e:
        acct = {"error": str(e)}

    # Make vs take at order creation (every placement, filled or not).
    mvt = [r for r in recs if r["action"] == "place" and r.get("take_price") is not None]
    recent_mvt = [r for r in mvt if since is None or r["ts"] > since]

    def mvt_agg(rows):
        if not rows:
            return None
        return {
            "n": len(rows),
            "avg_make_ev_pct": round(statistics.mean(r["ev_pct"] for r in rows), 2),
            "avg_take_ev_pct": round(statistics.mean(r["take_ev_pct"] for r in rows), 2),
            "avg_make_better_by_pct_pts": round(statistics.mean(r["make_vs_take_pct_pts"] for r in rows), 2),
            "avg_spread_pct_pts": round(statistics.mean(r["spread_pct_pts"] for r in rows if r.get("spread_pct_pts") is not None), 2),
            "take_also_plus_ev_share": round(sum(r["take_ev_pct"] >= 1.0 for r in rows) / len(rows), 3),
        }

    summary = {
        "at": now.isoformat(),
        "make_vs_take_at_creation": {"all": mvt_agg(mvt), "since_last_pass": mvt_agg(recent_mvt)},
        "process_alive": _alive(),
        "account": acct,
        "since_last_pass": {
            "places": sum(r["action"] == "place" for r in recent),
            "cancels": sum(r["action"] == "cancel" for r in recent),
            "fills": sum(r["action"] == "fill" for r in recent),
            "errors": sum(r["action"] == "error" for r in recent),
            "failsafes": [r.get("reason") for r in recent if r["action"] == "failsafe"],
            "error_samples": list({r.get("error", "")[:120] for r in recent if r["action"] == "error"})[:5],
        },
        "fills_total": len(state["fills"]),
        "fill_quality_all": agg(graded),
        "fill_quality_by_source": by_source,
        "fill_quality_by_market": {k: v for k, v in by_market.items() if v},
        "feed": {"stream_connected": feed.get("stream_connected"),
                 "snapshot_age_s": feed.get("snapshot_age_s"),
                 "candidates": len(feed.get("candidates") or [])},
    }

    state["last_run"] = now.isoformat()
    STATE.write_text(json.dumps(state))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a") as fh:
        fh.write(f"\n## Pass {now:%Y-%m-%d %H:%M} UTC\n\n```json\n{json.dumps(summary, indent=2)}\n```\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
