"""Novig auto-maker: post-only bids where the MAKE price is +EV vs fair.

Run (separate process from the API server):
    NOVIG_AUTOMAKER_MODE=shadow .venv/bin/python -m server.automaker.novig_maker

Modes (NOVIG_AUTOMAKER_MODE):
  off     default — exits immediately.
  shadow  computes and logs every place/cancel it WOULD make against a
          virtual bankroll; never loads the trading key, never calls Novig.
  live    places real-money post-only orders from the `trading` subaccount.
          Switching to live is the user's act.

Strategy (user-set, 2026-10-09):
  * EV is computed on the price we'd POST (one tick above the outcome's best
    bid, or joining it on a one-tick spread) — never the take price:
    EV = fair_prob / make_price - 1, must be >= MIN_EV (1%).
  * Size: KELLY_MULT (1/2) x full Kelly, f = (p - q) / (1 - q), each order
    against the FULL balance. Every +EV order is posted regardless of how
    much is already resting — whatever fills first wins, and Novig refuses
    fills the wallet can't cover. No exposure or loss caps (user's call).
  * Best EV first. Post-only (never takes), each order expires on its own
    after ORDER_TTL_S and is re-posted.

Event-driven (2026-10-09): the maker holds its own signed Novig websocket —
`bbo` for every candidate event plus PRIVATE `orders`/`positions` — so open
orders, positions and best bids are live state, not per-cycle REST polls. A
cycle runs ~DEBOUNCE_S after any relevant change (outbid, fill, position)
and at least every LOOP_S; fair prices refresh from the API every FEED_S;
REST re-syncs orders/positions every RECONCILE_S as a safety net.

Fail-safes (these guard against acting on BAD DATA, not against losing
bets): a kill file, an unreachable/stale candidate feed, or either Novig
stream being down each cancel every resting order and stop posting until
healthy.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..odds.books.novig.normalizer import next_tick, prob_to_american

logger = logging.getLogger("novig_automaker")

ROOT = Path(__file__).resolve().parents[2]
MODE = os.environ.get("NOVIG_AUTOMAKER_MODE", "off").strip().lower()
MIN_EV = float(os.environ.get("AUTOMAKER_MIN_EV_PCT", "1.0")) / 100.0
KELLY_MULT = float(os.environ.get("AUTOMAKER_KELLY_MULT", "0.5"))
LOOP_S = float(os.environ.get("AUTOMAKER_LOOP_S", "5"))
# 60 min (was 10): every expiry cancels + re-posts and loses queue priority.
# Safe to run long now that launchd restarts a crashed maker, and every
# start cancels all of its orders first.
ORDER_TTL_S = int(os.environ.get("AUTOMAKER_ORDER_TTL_S", "3600"))
REPOST_BEFORE_EXPIRY_S = 60
START_BUFFER_S = int(os.environ.get("AUTOMAKER_START_BUFFER_S", "120"))
MAX_SNAPSHOT_AGE_S = float(os.environ.get("AUTOMAKER_MAX_SNAPSHOT_AGE_S", "180"))
# Data-quality filters, same as the EV page's defaults: devig noise on
# longshots and EVs flagged low-confidence (likely stale/mispriced fair).
MAX_LONGSHOT_AMERICAN = int(os.environ.get("AUTOMAKER_MAX_LONGSHOT", "800"))
SKIP_LOW_CONFIDENCE = os.environ.get("AUTOMAKER_SKIP_LOW_CONFIDENCE", "true") != "false"
SHADOW_BANKROLL = float(os.environ.get("AUTOMAKER_SHADOW_BANKROLL", "2000"))
CANDIDATES_URL = os.environ.get(
    "AUTOMAKER_CANDIDATES_URL", "http://127.0.0.1:8000/api/novig/maker-candidates",
)
KILL_FILE = ROOT / "server" / "data" / "automaker.KILL"
LOG_PATH = ROOT / "logs" / "novig_automaker.jsonl"
FILLS_EVERY_S = 60
# Resize a resting EV order only when it's clearly off target (each re-post
# loses queue position): over by >10% of target, or under by >25%.
RESIZE_OVER = 0.10
RESIZE_UNDER = 0.25
# Hedge (arb) leg: once a position fills on side A at avg price q, post a
# make bid on side B one tick above B's best bid (b) while the matched pair
# locks at least this ROI: 1 / (q + b) - 1. Novig redeems matched pairs.
MIN_ARB_ROI = float(os.environ.get("AUTOMAKER_MIN_ARB_PCT", "1.5")) / 100.0
# Capital utilization = open position cost / (position cost + cash). At or
# above PAUSE the maker stops EV betting (cancels resting EV orders, posts no
# new ones) and only manages hedges; EV resumes below RESUME (hysteresis so
# it doesn't flap at the line). User's rule, 2026-10-09: pause at 90%, resume <85%.
# Hedges are NOT gated: they post on every fill at any utilization.
UTIL_PAUSE = float(os.environ.get("AUTOMAKER_UTIL_PAUSE_PCT", "90")) / 100.0
UTIL_RESUME = float(os.environ.get("AUTOMAKER_UTIL_RESUME_PCT", "85")) / 100.0
# Live placement pacing: the account's `place` bucket refills 8/s (cap 256);
# `cancel` refills 16/s.
PLACE_GAP_S = float(os.environ.get("AUTOMAKER_PLACE_GAP_S", "0.16"))
CANCEL_GAP_S = float(os.environ.get("AUTOMAKER_CANCEL_GAP_S", "0.08"))
DEBOUNCE_S = 0.25          # coalesce a burst of stream events into one cycle
FEED_S = 5.0               # fair-price / candidate refresh from the API
MAX_FEED_AGE_S = 20.0      # older than this -> fail-safe
RECONCILE_S = 30.0         # REST re-sync of orders + positions
BALANCE_S = 10.0           # REST balance refresh
SUMMARY_EVERY_S = 30.0     # cycle summary log line cadence when idle


def make_price(c: dict) -> float | None:
    """The price we'd post: one tick above the outcome's best bid, or the
    bid itself when that would reach the take price (one-tick spread)."""
    own, opp = c.get("own_best_bid"), c.get("other_best_bid")
    if not own:
        return None
    bid = float(own[0])
    q = next_tick(bid)
    take = None if not opp else 1.0 - float(opp[0])
    if q is None or (take is not None and q >= take - 1e-9):
        q = bid
    return round(q, 3) if 0.0 < q < 1.0 else None


def ev_at(fair: float, q: float) -> float:
    return fair / q - 1.0


def kelly_target(fair: float, q: float, bankroll: float) -> float:
    """Half-Kelly TARGET total stake ($) on one outcome at price q."""
    f = (fair - q) / (1.0 - q)
    return KELLY_MULT * max(f, 0.0) * bankroll


def kelly_qty(fair: float, q: float, bankroll: float, held: float = 0.0) -> tuple[int, float]:
    """(contracts, cost $) still to post so that what's already filled on
    this outcome (`held`, $ at cost) plus this order reaches the half-Kelly
    target — never beyond it. A contract pays $0.01; cost = qty x q x $0.01."""
    stake = kelly_target(fair, q, bankroll) - max(held, 0.0)
    if stake <= 0:
        return 0, 0.0
    qty = int(math.floor(stake * 100.0 / q))
    return qty, qty * q / 100.0


def net_positions(positions: list[dict]) -> list[dict]:
    """Net each binary market's two sides. Novig pays out matched pairs as
    SETTLEMENT cash but /portfolio/positions keeps listing BOTH sides at full
    size (verified live 2026-10-09: 13 markets, 17 payouts, quantities
    unchanged). Exposure is the excess on the bigger side, at its avg cost."""
    by_market: dict[str, list[dict]] = {}
    for p in positions:
        if int(p.get("qty") or 0) > 0:
            by_market.setdefault(p["marketId"], []).append(p)
    out: list[dict] = []
    for ps in by_market.values():
        if len(ps) != 2:
            out.extend(ps)
            continue
        big, small = sorted(ps, key=lambda p: -int(p["qty"]))
        rq = int(big["qty"]) - int(small["qty"])
        if rq <= 0:
            continue
        avg = float(big["cost"]) / int(big["qty"])
        out.append({**big, "qty": rq, "cost": f"{rq * avg:.5f}"})
    return out


def load_hedge_ids(path: Path) -> dict[str, dict]:
    """Hedge orders survive a restart: without this, resting hedges look like
    foreign bids (hedge_plan then thinks it must outbid them, and the 90%
    pause would cancel them as EV orders). Orders since gone are harmless —
    lookups are by live orderId."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            if '"hedge_place"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("mode") == "live" and r.get("order_id"):
                out[r["order_id"]] = r
    return out


class Maker:
    def __init__(self, mode: str):
        self.mode = mode
        self.trader = None
        if mode == "live":
            from ..odds.books.novig.trading import NovigTrader
            self.trader = NovigTrader()
        self.http = httpx.AsyncClient(timeout=30.0)
        # shadow: outcome_id -> virtual order
        self.virtual: dict[str, dict] = {}
        # live hedge orders we placed: order_id -> hedge plan. In memory only;
        # startup cancels every order, so nothing outlives a restart.
        self.hedge_ids: dict[str, dict] = {}
        self.ev_paused = False
        # Live state from the private stream (REST re-sync every RECONCILE_S).
        self.orders: dict[str, dict] = {}       # orderId -> open order
        self.gross_pos: dict[str, dict] = {}    # outcomeId -> position (gross)
        self.priv_ready = mode != "live"
        self.feed: dict | None = None
        self.feed_at = 0.0
        self._balance = (0.0, 0.0)              # (value, monotonic time)
        self.interesting: set[str] = set()      # market ids worth waking for
        self.wake = asyncio.Event()
        self.last_summary = 0.0
        self.stream = self._make_stream()
        self.failsafe_active = False
        self.last_fills_ms = int(time.time() * 1000)
        self.last_fills_check = 0.0
        self.stop = asyncio.Event()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if mode == "live":
            self.hedge_ids.update(load_hedge_ids(LOG_PATH))
        self._log = LOG_PATH.open("a")

    def log(self, action: str, **fields) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "mode": self.mode,
               "action": action, **fields}
        self._log.write(json.dumps(rec, default=str) + "\n")
        self._log.flush()

    # ───────────────────────── exchange views ─────────────────────────

    async def open_orders(self) -> list[dict]:
        if self.mode == "live":
            return list(self.orders.values())
        return [dict(o, outcomeId=oid) for oid, o in self.virtual.items()]

    async def cash(self) -> float:
        if self.mode == "live":
            value, at = self._balance
            if time.monotonic() - at > BALANCE_S:
                value = await self.trader.balance()
                self._balance = (value, time.monotonic())
            return value
        tied = sum(o["qty"] * float(o["price"]) / 100.0 for o in self.virtual.values())
        return SHADOW_BANKROLL - tied

    # ───────────────────────── live streams ─────────────────────────

    def _make_stream(self):
        from ..odds.books.novig.ws_feed import NovigBboStream
        if self.mode == "live":
            from ..odds.books.novig.client import _Signer
            from ..odds.books.novig.trading import CONFIG_PATH
            cfg = json.loads(CONFIG_PATH.read_text())
            signer = _Signer(cfg["key_id"], Path(cfg["pem"]).expanduser())
            private = ("orders", "positions")
        else:
            from ..odds.books.novig.client import _signer_from_env
            signer, private = _signer_from_env(), ()
            if signer is None:
                return None
        return NovigBboStream(
            signer, desired=self._stream_desired,
            on_change=self._on_bbo_change, on_lost=lambda _m: self.wake.set(),
            private=private, on_private=self._on_private if private else None,
        )

    def _stream_desired(self) -> list[tuple[str, int]]:
        """Novig events to watch, soonest game first, from the candidate feed."""
        if not self.feed:
            return []
        seen: dict[str, tuple[str, int]] = {}
        for c in self.feed.get("candidates") or []:
            eid = c.get("novig_event_id")
            if eid and eid not in seen:
                seen[eid] = (c["commence_time"], int(c.get("novig_event_market_count") or 1))
        return [(eid, n) for eid, (_, n) in sorted(seen.items(), key=lambda kv: kv[1][0])]

    def _on_bbo_change(self, market_id: str) -> None:
        if market_id in self.interesting:
            self.wake.set()

    def _on_private(self, msg: dict) -> None:
        o, p = msg.get("orders"), msg.get("positions")
        if o:
            if "open" in o:                      # subscribe snapshot
                self.orders = {x["orderId"]: x for x in o["open"]}
                self.priv_ready = True
            for d in o.get("deltas") or []:
                kind, oid = d.get("kind"), d.get("orderId")
                if kind == "open":
                    self.orders[oid] = {k: v for k, v in d.items() if k != "kind"}
                elif kind == "fill":
                    rem = int(d.get("remaining") or 0)
                    if rem > 0 and oid in self.orders:
                        self.orders[oid]["qty"] = rem
                    else:
                        self.orders.pop(oid, None)
                    self.log("fill_event", order_id=oid, outcome_id=d.get("outcomeId"),
                             price=d.get("price"), qty=d.get("qty"), remaining=rem,
                             hedge=oid in self.hedge_ids)
                elif kind in ("cancel", "reject"):
                    self.orders.pop(oid, None)
                    if kind == "reject":
                        self.log("reject", order_id=oid)
        if p:
            if "positions" in p:
                self.gross_pos = {x["outcomeId"]: x for x in p["positions"]}
            for d in p.get("deltas") or []:
                if int(d.get("qty") or 0) > 0:
                    self.gross_pos[d["outcomeId"]] = d
                else:
                    self.gross_pos.pop(d["outcomeId"], None)
        self.wake.set()

    async def _feed_loop(self) -> None:
        while not self.stop.is_set():
            try:
                r = await self.http.get(CANDIDATES_URL)
                r.raise_for_status()
                self.feed, self.feed_at = r.json(), time.monotonic()
            except Exception as e:
                logger.warning("candidate feed: %s", e)
            await asyncio.sleep(FEED_S)

    async def _reconcile_loop(self) -> None:
        """REST is the ground truth: periodically replace stream-built state."""
        while not self.stop.is_set():
            await asyncio.sleep(RECONCILE_S)
            try:
                orders = await self.trader.open_orders()
                positions = await self.trader.positions()
            except Exception as e:
                self.log("error", op="reconcile", error=str(e))
                continue
            rest_ids = {x["orderId"] for x in orders}
            drift = len(rest_ids ^ set(self.orders))
            self.orders = {x["orderId"]: x for x in orders}
            self.gross_pos = {x["outcomeId"]: x for x in positions}
            if drift:
                self.log("reconcile", order_id_drift=drift)
            self.wake.set()

    async def cancel(self, order: dict, reason: str, cand: dict | None) -> None:
        if self.mode == "live":
            from ..odds.books.novig.trading import NovigTradeError
            try:
                await self.trader.cancel(order["orderId"])
            except NovigTradeError as e:
                if e.status != 404:
                    self.log("error", op="cancel", order_id=order["orderId"], error=str(e))
                    return
                # Already filled or expired between our read and the cancel.
                reason = f"{reason} (already gone)"
            self.orders.pop(order["orderId"], None)
            await asyncio.sleep(CANCEL_GAP_S)
        else:
            self.virtual.pop(order["outcomeId"], None)
        self.log("cancel", reason=reason, order_id=order.get("orderId"),
                 outcome_id=order["outcomeId"], price=order.get("price"),
                 qty=order.get("qty"), **_desc(cand))

    async def cancel_everything(self, reason: str) -> None:
        if self.mode == "live":
            try:
                n = await self.trader.cancel_all()
            except Exception as e:
                self.log("error", op="cancel_all", error=str(e))
                return
        else:
            n = len(self.virtual)
            self.virtual.clear()
        self.log("failsafe", reason=reason, canceled=n)
        logger.warning("fail-safe (%s): canceled %d orders", reason, n)

    async def place(self, cand: dict, q: float, qty: int, ev: float) -> bool:
        oid = cand["outcome_id"]
        expires = datetime.now(timezone.utc) + timedelta(seconds=ORDER_TTL_S)
        order_id = None
        if self.mode == "live":
            from ..odds.books.novig.trading import NovigTradeError
            try:
                resp = await self.trader.place_post_only(oid, q, qty, ORDER_TTL_S * 1000)
                order_id = resp.get("orderId")
                # Visible to the next cycle before the stream's `open` lands.
                self.orders[order_id] = {
                    "orderId": order_id, "outcomeId": oid, "marketId": cand.get("market_id"),
                    "price": f"{q:.3f}", "qty": qty,
                    "expiresAt": int(expires.timestamp() * 1000)}
            except NovigTradeError as e:
                self.log("error", op="place", outcome_id=oid, price=q, qty=qty,
                         error=str(e), **_desc(cand))
                if e.status in (403, 423, 451):
                    # Account/geo refusal: nothing will place; stop and say so.
                    logger.error("placement refused (%s); pausing 5 min", e)
                    await asyncio.sleep(300)
                    return False
                if e.status == 429:
                    await asyncio.sleep(2.0)
                # Anything else (incl. INSUFFICIENT_BALANCE): skip this one,
                # keep posting the rest.
                return True
        else:
            self.virtual[oid] = {"orderId": f"shadow-{oid[:8]}", "price": f"{q:.3f}",
                                 "qty": qty, "expiresAt": int(expires.timestamp() * 1000)}
        # Make vs take AT CREATION: what taking this side would have cost
        # right now (1 - the other side's best bid), and its EV.
        opp = cand.get("other_best_bid")
        own = cand.get("own_best_bid")
        take = round(1.0 - float(opp[0]), 4) if opp else None
        fair = cand["fair_probability"]
        self.log("place", order_id=order_id, outcome_id=oid, price=q,
                 price_american=prob_to_american(q), qty=qty,
                 cost=round(qty * q / 100.0, 2), ev_pct=round(ev * 100, 2),
                 fair=round(fair, 4),
                 take_price=take,
                 take_price_american=prob_to_american(take) if take else None,
                 take_ev_pct=round(ev_at(fair, take) * 100, 2) if take else None,
                 make_vs_take_pct_pts=round((take - q) * 100, 2) if take else None,
                 best_bid=float(own[0]) if own else None,
                 spread_pct_pts=round((take - float(own[0])) * 100, 2) if take and own else None,
                 **_desc(cand))
        return True

    # ───────────────────────── one cycle ─────────────────────────

    async def cycle(self) -> None:
        now = datetime.now(timezone.utc)
        if KILL_FILE.exists():
            if not self.failsafe_active:
                await self.cancel_everything("kill file")
                self.failsafe_active = True
            return
        feed = self.feed
        if feed is None and self.feed_at == 0.0:
            return          # startup: first candidate fetch hasn't landed yet
        feed_age = time.monotonic() - self.feed_at
        own_ok = self.stream is not None and self.stream.connected and self.priv_ready
        age = (feed or {}).get("snapshot_age_s")
        problem = None
        if feed is None or feed_age > MAX_FEED_AGE_S:
            problem = f"candidate feed stale ({feed_age:.0f}s)"
        elif not feed.get("stream_connected") or age is None or age > MAX_SNAPSHOT_AGE_S:
            problem = f"stale data (api stream={feed.get('stream_connected')}, snapshot_age={age})"
        elif not own_ok:
            problem = "maker stream down"
        if problem:
            if not self.failsafe_active:
                await self.cancel_everything(problem)
                self.failsafe_active = True
            return
        if self.failsafe_active:
            self.log("failsafe_cleared")
            self.failsafe_active = False

        # Best bids from the maker's OWN stream (live) where it covers the
        # market; otherwise the API's copy (<= FEED_S old).
        cands: dict[str, dict] = {}
        for c in feed["candidates"]:
            mid = c["market_id"]
            if self.stream is not None and self.stream.covers(mid):
                lv = self.stream.state.get(mid, {})
                own, opp = lv.get(c["outcome_id"]), lv.get(c.get("other_outcome_id"))
                c = dict(c, own_best_bid=list(own) if own else None,
                         other_best_bid=list(opp) if opp else None, bbo_live=True)
            elif not c.get("bbo_live"):
                continue
            cands[c["outcome_id"]] = c
        cutoff = now + timedelta(seconds=START_BUFFER_S)
        now_ms = now.timestamp() * 1000

        orders = await self.open_orders()
        positions: list[dict] = []
        if self.mode == "live":
            positions = net_positions(list(self.gross_pos.values()))
        hedge_want = self.hedge_plan(cands, orders, cutoff, positions) if self.mode == "live" else {}

        # Capital utilization gate for EV betting (hedges always run).
        util = None
        if self.mode == "live":
            pos_cost = sum(float(p.get("cost") or 0) for p in positions)
            balance = await self.cash()
            util = pos_cost / (pos_cost + balance) if (pos_cost + balance) > 0 else 0.0
            if not self.ev_paused and util >= UTIL_PAUSE:
                self.ev_paused = True
                self.log("ev_paused", utilization=round(util, 4), positions_cost=round(pos_cost, 2), cash=round(balance, 2))
                logger.warning("EV betting PAUSED: utilization %.1f%% >= %.0f%%", util * 100, UTIL_PAUSE * 100)
            elif self.ev_paused and util < UTIL_RESUME:
                self.ev_paused = False
                self.log("ev_resumed", utilization=round(util, 4), positions_cost=round(pos_cost, 2), cash=round(balance, 2))
                logger.warning("EV betting RESUMED: utilization %.1f%% < %.0f%%", util * 100, UTIL_RESUME * 100)

        self.interesting = (
            {c["market_id"] for c in cands.values()}
            | {o.get("marketId") for o in orders}
            | {p.get("marketId") for p in positions}
        )

        # Sizing inputs: equity bankroll and what's already filled per outcome.
        if self.mode == "live":
            # Size against total equity (cash + open positions at cost), not
            # cash alone: cash shrinks as orders fill, which was shrinking
            # every new bet even though the bankroll hadn't changed.
            bankroll = balance + sum(float(p.get("cost") or 0) for p in positions)
        else:
            bankroll = SHADOW_BANKROLL
        held = {p["outcomeId"]: float(p.get("cost") or 0) for p in positions}

        # 0. Review our hedge orders: keep only those still wanted as-is.
        hedge_kept: set[str] = set()
        touched: set[str] = set()
        ev_orders = []
        for o in orders:
            plan = self.hedge_ids.get(o.get("orderId"))
            if plan is None:
                ev_orders.append(o)
                continue
            oid = o["outcomeId"]
            want = hedge_want.get(oid)
            reason = None
            if want is None:
                reason = "arb no longer >= threshold"
            elif abs(float(o["price"]) - want["price"]) > 1e-9:
                reason = "reprice"
            elif abs(int(o["qty"]) - want["qty"]) > max(1, 0.05 * want["qty"]):
                reason = "resize"
            elif o.get("expiresAt") and o["expiresAt"] - now_ms < REPOST_BEFORE_EXPIRY_S * 1000:
                reason = "expiring"
            if reason:
                await self.cancel(o, f"hedge: {reason}", cands.get(oid))
                self.hedge_ids.pop(o["orderId"], None)
                touched.add(oid)
            else:
                hedge_kept.add(oid)

        # 1. Review resting EV orders.
        kept: dict[str, dict] = {}
        for o in ev_orders:
            oid = o["outcomeId"]
            if self.ev_paused:
                await self.cancel(o, "paused: capital utilization", cands.get(oid))
                touched.add(oid)
                continue
            if oid in hedge_want:
                # The hedge leg owns this outcome; its price is computed with
                # this bid gone, so post the hedge next cycle.
                await self.cancel(o, "replaced by hedge", cands.get(oid))
                touched.add(oid)
                continue
            c = cands.get(oid)
            price = float(o["price"])
            reason = None
            if c is None:
                reason = "no longer a candidate"
            elif datetime.fromisoformat(c["commence_time"]) <= cutoff:
                reason = "game starting"
            elif oid in kept:
                reason = "duplicate"
            elif ev_at(c["fair_probability"], price) < MIN_EV:
                reason = "ev below threshold"
            elif c["own_best_bid"] and float(c["own_best_bid"][0]) > price + 1e-9:
                reason = "outbid"
            elif o.get("expiresAt") and o["expiresAt"] - now_ms < REPOST_BEFORE_EXPIRY_S * 1000:
                reason = "expiring"
            else:
                # Size check: filled + this order must track the current
                # half-Kelly target, never stack past it.
                target = kelly_target(c["fair_probability"], price, bankroll)
                want = target - held.get(oid, 0.0)
                have = int(o["qty"]) * price / 100.0
                if have > want + RESIZE_OVER * target:
                    reason = "resize down (over target)"
                elif want - have > RESIZE_UNDER * target:
                    reason = "resize up (under target)"
            if reason:
                await self.cancel(o, reason, c)
                if reason != "outbid":
                    touched.add(oid)
                # Outbid: someone else holds the best bid, so the bbo already
                # excludes ours — re-quote one tick above them THIS cycle
                # instead of waiting 5s and losing more queue position.
            else:
                kept[oid] = o

        # 2. Post where the make price clears the threshold, best EV first.
        # User's choice (2026-10-09): post EVERY +EV order, each sized at
        # half Kelly of the full balance, regardless of how much is already
        # resting — whatever fills first wins; Novig refuses fills the
        # wallet can't cover. Open orders do not reduce the bankroll (Novig's
        # balance doesn't drop while orders rest either — verified live).
        # 2a. Hedge legs first: they lock profit on filled positions.
        hedged = 0
        for oid, want in hedge_want.items():
            if oid in hedge_kept or oid in touched:
                continue
            if await self.place_hedge(want):
                hedged += 1
                await asyncio.sleep(PLACE_GAP_S)

        plans = []
        if self.ev_paused:
            cands_for_ev = {}
        else:
            cands_for_ev = cands
        for oid, c in cands_for_ev.items():
            if oid in kept or oid in touched or oid in hedge_want:
                continue  # touched: our own cancelled bid may still show in the bbo
            if datetime.fromisoformat(c["commence_time"]) <= cutoff:
                continue
            if SKIP_LOW_CONFIDENCE and c.get("confidence") == "low":
                continue
            q = make_price(c)
            if q is None:
                continue
            am = prob_to_american(q)
            if am is None or am > MAX_LONGSHOT_AMERICAN:
                continue
            ev = ev_at(c["fair_probability"], q)
            if ev >= MIN_EV:
                plans.append((ev, c, q))
        plans.sort(key=lambda x: -x[0])
        placed = 0
        posted = 0.0
        for ev, c, q in plans:
            qty, cost = kelly_qty(c["fair_probability"], q, bankroll, held.get(c["outcome_id"], 0.0))
            if qty < 1:
                continue   # already holding the full target on this outcome
            ok = await self.place(c, q, qty, ev)
            if not ok:
                break
            placed += 1
            posted += cost
            if self.mode == "live":
                await asyncio.sleep(PLACE_GAP_S)   # stay under the 8/s place bucket

        resting = sum(int(o["qty"]) * float(o["price"]) / 100.0 for o in kept.values()) + posted
        await self.log_fills()
        acted = placed or hedged or touched
        if not acted and time.monotonic() - self.last_summary < SUMMARY_EVERY_S:
            return
        self.last_summary = time.monotonic()
        logger.info(
            "cycle: %d candidates, %d +EV, kept %d, cancelled %d, placed %d, "
            "hedges wanted %d (resting %d, posted %d), resting $%.2f vs bankroll $%.2f, "
            "utilization %s%s",
            len(cands), len(plans), len(kept), len(touched), placed,
            len(hedge_want), len(hedge_kept), hedged, resting, bankroll,
            "n/a" if util is None else f"{util * 100:.1f}%",
            " [EV PAUSED]" if self.ev_paused else "",
        )

    # ───────────────────────── hedge (arb) leg ─────────────────────────

    def hedge_plan(self, cands: dict, orders: list[dict], cutoff: datetime,
                   positions: list[dict]) -> dict:
        """outcome_id (side B) -> hedge plan for every filled position (side A)
        whose opposite make price locks >= MIN_ARB_ROI on the matched pair."""
        by_market: dict[str, dict[str, dict]] = {}
        for c in cands.values():
            by_market.setdefault(c["market_id"], {})[c["outcome_id"]] = c
        our_hedge_price = {
            o["outcomeId"]: float(o["price"]) for o in orders
            if o.get("orderId") in self.hedge_ids
        }
        want: dict[str, dict] = {}
        for p in positions:
            qty = int(p.get("qty") or 0)
            if qty < 1:
                continue
            q = float(p["cost"]) * 100.0 / qty          # avg entry price on side A
            mc = by_market.get(p["marketId"], {})
            ca = mc.get(p["outcomeId"])
            b_out = (ca or {}).get("other_outcome_id") or next(
                (o for o in mc if o != p["outcomeId"]), None)
            cb = mc.get(b_out) if b_out else None
            if cb is not None:
                view, ref = cb, cb
            elif ca is not None:
                view = {"own_best_bid": ca["other_best_bid"], "other_best_bid": ca["own_best_bid"]}
                ref = ca
            else:
                continue
            if datetime.fromisoformat(ref["commence_time"]) <= cutoff:
                continue
            mine = our_hedge_price.get(b_out)
            top = view.get("own_best_bid")
            if mine is not None and top and abs(float(top[0]) - mine) < 1e-9:
                b = mine                    # we ARE the best bid: don't outbid ourselves
            else:
                b = make_price(view)        # one tick above B's best bid
            if b is None:
                continue
            roi = 1.0 / (q + b) - 1.0
            if roi < MIN_ARB_ROI:
                continue
            want[b_out] = {
                "outcome_id": b_out, "market_id": p["marketId"], "price": b,
                "qty": qty, "entry_price": round(q, 4), "roi": roi,
                "position_outcome_id": p["outcomeId"], "cand": ref,
            }
        return want

    async def place_hedge(self, want: dict) -> bool:
        from ..odds.books.novig.trading import NovigTradeError
        try:
            resp = await self.trader.place_post_only(
                want["outcome_id"], want["price"], want["qty"], ORDER_TTL_S * 1000)
        except NovigTradeError as e:
            self.log("error", op="hedge_place", outcome_id=want["outcome_id"],
                     price=want["price"], qty=want["qty"], error=str(e))
            return False
        self.hedge_ids[resp["orderId"]] = want
        self.orders[resp["orderId"]] = {
            "orderId": resp["orderId"], "outcomeId": want["outcome_id"],
            "marketId": want["market_id"], "price": f"{want['price']:.3f}", "qty": want["qty"],
            "expiresAt": int((time.time() + ORDER_TTL_S) * 1000)}
        self.log("hedge_place", order_id=resp["orderId"], outcome_id=want["outcome_id"],
                 price=want["price"], price_american=prob_to_american(want["price"]),
                 qty=want["qty"], cost=round(want["qty"] * want["price"] / 100.0, 2),
                 entry_price=want["entry_price"], arb_roi_pct=round(want["roi"] * 100, 2),
                 locked_if_filled=round(want["qty"] * (1 - want["entry_price"] - want["price"]) / 100.0, 2),
                 position_outcome_id=want["position_outcome_id"], **_desc(want["cand"]))
        return True

    async def log_fills(self) -> None:
        if self.mode != "live" or time.monotonic() - self.last_fills_check < FILLS_EVERY_S:
            return
        self.last_fills_check = time.monotonic()
        try:
            fills = await self.trader.fills_since(self.last_fills_ms)
        except Exception as e:
            self.log("error", op="fills", error=str(e))
            return
        for f in fills:
            fill_ts = int(f.get("ts") or 0)
            self.log("fill", fill_ts=fill_ts, **{k: v for k, v in f.items() if k != "ts"})
            self.last_fills_ms = max(self.last_fills_ms, fill_ts)

    async def run(self) -> None:
        self.log("start", min_ev=MIN_EV, kelly_mult=KELLY_MULT, ttl_s=ORDER_TTL_S)
        logger.info("novig auto-maker running in %s mode", self.mode.upper())
        if self.mode == "live":
            # Start from a clean book: nothing left over from a previous run.
            await self.cancel_everything("startup")
            self.failsafe_active = False
        tasks = [asyncio.create_task(self._feed_loop())]
        if self.stream is not None:
            tasks.append(asyncio.create_task(self.stream.run()))
        if self.mode == "live":
            tasks.append(asyncio.create_task(self._reconcile_loop()))
        try:
            while not self.stop.is_set():
                waker = asyncio.create_task(self.wake.wait())
                stopper = asyncio.create_task(self.stop.wait())
                await asyncio.wait({waker, stopper}, timeout=LOOP_S,
                                   return_when=asyncio.FIRST_COMPLETED)
                waker.cancel(); stopper.cancel()
                if self.stop.is_set():
                    break
                await asyncio.sleep(DEBOUNCE_S)   # coalesce the burst
                self.wake.clear()
                try:
                    await self.cycle()
                except Exception:
                    logger.exception("cycle failed")
                    self.log("error", op="cycle")
        finally:
            for t in tasks:
                t.cancel()
            await self.cancel_everything("shutdown")
            self.log("stop")
            await self.http.aclose()
            if self.trader is not None:
                await self.trader.aclose()


def _desc(c: dict | None) -> dict:
    if not c:
        return {}
    return {k: c.get(k) for k in ("sport_key", "away_team", "home_team", "market_key",
                                  "outcome_name", "point", "fair_source")}


async def _main() -> None:
    if MODE not in ("shadow", "live"):
        print(f"NOVIG_AUTOMAKER_MODE={MODE!r}: auto-maker is off. Set shadow or live.")
        return
    maker = Maker(MODE)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, maker.stop.set)
    await maker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_main())
