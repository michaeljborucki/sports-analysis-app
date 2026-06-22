"""Coral33 bet-placement client — pure builders + Coral33Placer class.

The builders below are pure functions: they produce the exact JSON body
shape Coral33's web client sends. Byte-accuracy tests under
server/tests/test_coral33_placement.py compare them against HAR fixtures.

The Coral33Placer class wraps the builders with the network layer (uses
Coral33Client's authenticated session) and orchestrates the five-call
chain into a single place_open_parlay() method.

Kill switch:
  - Per-call live: bool — defaults to False (dry-run halts before step 4)
  - Module env CORAL33_PLACEMENT_LIVE=true — must be set for live placements
  - No instance is constructed by any API route or scheduler until the
    explicit wiring task lands.

See docs/superpowers/specs/2026-06-21-auto-bet-sidecar-design.md.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from server.sidecar.models import LegSpec


CUSTOMER_ID_WIDTH = 10


def _padded(customer_id: str) -> str:
    return customer_id + " " * max(0, CUSTOMER_ID_WIDTH - len(customer_id))


# --- Builders ----------------------------------------------------------------

def build_get_parlay_specs(customer_id: str, parlay_name: str) -> dict:
    return {
        "customerID": _padded(customer_id),
        "parlayName": parlay_name,
        "operation": "getParlaySpecs",
        "RRO": 1,
    }


def build_get_info_parlay(
    customer_id: str,
    parlay_name: str,
    teams: int,
    selects: str,
) -> dict:
    return {
        "customerID": _padded(customer_id),
        "teams": teams,
        "parlayName": parlay_name,
        "selects": selects,
        "operation": "getInfoParlay",
        "RRO": 1,
    }


def build_check_wager_line_multi_parlay(
    customer_id: str,
    leg: LegSpec,
    position: int,
    risk_dollars: float,
    win_dollars: float,
) -> dict:
    return {
        "list": [
            {
                "position": position,
                "gameNum": leg.game_num,
                "contestantNum": 0,
                "periodNumber": 0,
                "store": "wiseguys",
                "status": "O",
                "profile": ".",
                "periodType": leg.period,
                "description": leg.description,
                "risk": f"{risk_dollars:g}",
                "win": f"{win_dollars:g}",
                "wagerType": "P",
            }
        ],
        "customerID": _padded(customer_id),
        "operation": "checkWagerLineMulti",
        "RRO": 0,
    }


def build_insert_wager_parlay(
    customer_id: str,
    agent_id: str,
    store: str,
    cust_profile: str,
    leg: LegSpec,
    stake_dollars: float,
    win_dollars: float,
    decimal_win_amount: float,
    parlay_name: str,
    doc_num: int,
    delay: dict,
) -> dict:
    """Build the insertWagerParlay body. Matches the HAR's entry-41 schema."""
    padded = _padded(customer_id)
    today = time.strftime("%Y-%m-%d")
    return {
        "customerID": padded,
        "list": [
            {
                "customerID": padded,
                "docNum": doc_num,
                "wagerType": "P",
                "gameNum": leg.game_num,
                "wagerCount": 1,
                "gameDate": leg.game_datetime,
                "sportType": leg.sport_type,
                "sportSubType": leg.sport_sub_type,
                "lineType": leg.line_type,
                "adjSpread": 0,
                "adjTotal": 0,
                "priceType": "A",
                "finalMoney": leg.price_american,
                "finalDecimal": leg.price_decimal,
                "finalNumerator": leg.price_numerator,
                "finalDenominator": leg.price_denominator,
                "chosenTeamID": leg.chosen_team_id,
                "riskAmount": stake_dollars,
                "winAmount": decimal_win_amount,
                "store": store,
                "custProfile": cust_profile,
                "periodNumber": 0,
                "periodDescription": leg.period,
                "oddsFlag": "Y",
                "listedPitcher1": None,
                "pitcher1ReqFlag": "",
                "listedPitcher2": None,
                "pitcher2ReqFlag": "",
                "percentBook": 100,
                # volumeAmount per HAR: round(min(risk, win) * 100). For
                # +odds underdogs this collapses to stake*100; for favorites
                # (where win < stake) it uses win*100. Verified against both
                # HAR samples (straight $5.15/$5 → 500; parlay $10/$47.5 → 1000).
                "volumeAmount": round(min(stake_dollars, decimal_win_amount) * 100),
                "currencyCode": "USD",
                "date": today,
                "agentID": agent_id,
                "easternLine": 0,
                "origPrice": leg.price_american,
                "origDecimal": leg.price_decimal,
                "origNumerator": leg.price_numerator,
                "origDenominator": leg.price_denominator,
                "creditAcctFlag": "Y",
                "wager": {
                    "date": today,
                    "minPicks": 1,
                    "totalPicks": 2,
                    "wagerCount": 1,
                    "riskAmount": stake_dollars,
                    "winAmount": f"{win_dollars:.2f}",
                    "description": leg.description,
                    "lineType": "P",
                    "freePlay": "N",
                    "agentID": agent_id,
                    "currencyCode": "USD",
                    "creditAcctFlag": "Y",
                    "playNumber": 1,
                    "roundRobin": 0,
                    "parlayName": parlay_name,
                    "openSpotFlag": "O",
                    "parlayPayOutType": "R",
                    "maxPayOut": 1000000,
                    "update": False,
                    "team": 2,
                },
                "itemNumber": 1,
                "wagerNumber": 1,
                "origSpread": leg.price_american,
                "origTotal": leg.price_american,
                "origMoney": leg.price_american,
                "roundRobin": "0",
                "extra": {
                    "team1": "",
                    "team2": leg.chosen_team_id,
                    "rot1": 0,
                    "rot2": leg.rot_num,
                    "line": f"{leg.price_american:+d}",
                    "buy": False,
                    "point": 0,
                },
                "status": "O",
            }
        ],
        "agentView": False,
        "operation": "insertWagerParlay",
        "delay": delay,
    }


def build_get_pending_by_ticket(
    agent_id: str, customer_id: str, ticket_number: int
) -> dict:
    return {
        "agentID": agent_id,
        "customerID": _padded(customer_id),
        "ticketNumber": ticket_number,
        "path": "/cloud/api/Report/getPendingByTicket",
        "RRO": 0,
    }


# --- Coral33Placer -----------------------------------------------------------

@dataclass
class PlacementResult:
    ticket_number: int | None
    dry_run: bool
    accepted_payload: dict | None
    would_be_payload: dict | None     # set in dry-run; the body that WOULD have been sent
    decimal_payout: float             # from getInfoParlay × leg's decimal odds
    expected_win: float               # decimal_payout × stake - stake


class PlacementError(Exception):
    """Raised when the placement cannot proceed (sig missing, env gate, etc.)."""


class Coral33Placer:
    """Orchestrates the five-call open-spot parlay placement chain."""

    LIVE_ENV_VAR = "CORAL33_PLACEMENT_LIVE"

    def __init__(
        self,
        client: Any,                  # Coral33Client or FakeCoral33Client
        agent_id: str,
        store: str,
        cust_profile: str,
        parlay_name: str = "10 team",
    ):
        self.client = client
        self.agent_id = agent_id
        self.store = store
        self.cust_profile = cust_profile
        self.parlay_name = parlay_name
        self._specs_cache: dict | None = None

    async def place_open_parlay(
        self,
        ev_leg: LegSpec,
        stake_dollars: float,
        live: bool = False,
    ) -> PlacementResult:
        if live and os.environ.get(self.LIVE_ENV_VAR, "").lower() != "true":
            raise PlacementError(
                f"live placement requires {self.LIVE_ENV_VAR}=true"
            )

        # 1. getParlaySpecs (cached per Placer instance)
        if self._specs_cache is None:
            self._specs_cache = await self.client.post_json(
                "getParlaySpecs",
                build_get_parlay_specs(self.client.customer_id, self.parlay_name),
            )

        # 2. getInfoParlay — payout multiplier for a 2-team card
        selects = f"{ev_leg.game_num}-{ev_leg.line_type}|{ev_leg.chosen_team_id}^0"
        info = await self.client.post_json(
            "getInfoParlay",
            build_get_info_parlay(
                customer_id=self.client.customer_id,
                parlay_name=self.parlay_name,
                teams=2,
                selects=selects,
            ),
        )
        two_team_card = next(
            (c for c in info["INFO"]["CARD"] if c["GamesPicked"] == 2),
            None,
        )
        if two_team_card is None:
            raise PlacementError("getInfoParlay missing 2-team card row")
        decimal_multiplier = two_team_card["MoneyLine"]
        decimal_payout = ev_leg.price_decimal * decimal_multiplier
        expected_win = decimal_payout * stake_dollars - stake_dollars
        decimal_win_amount = ev_leg.price_decimal * stake_dollars - stake_dollars

        # 3. checkWagerLineMulti — line snapshot + DELAY.sig
        position = int(time.time() * 1000) % 10**8   # client-side unique id
        check = await self.client.post_json(
            "checkWagerLineMulti",
            build_check_wager_line_multi_parlay(
                customer_id=self.client.customer_id,
                leg=ev_leg,
                position=position,
                risk_dollars=stake_dollars,
                win_dollars=expected_win,
            ),
        )
        delay = check.get("DELAY")
        if not delay or "sig" not in delay:
            raise PlacementError("checkWagerLineMulti returned no DELAY.sig")

        # Build the insert payload regardless of mode (audit/preview)
        doc_num = int(time.time() * 1000) % 10**8
        insert_body = build_insert_wager_parlay(
            customer_id=self.client.customer_id,
            agent_id=self.agent_id,
            store=self.store,
            cust_profile=self.cust_profile,
            leg=ev_leg,
            stake_dollars=stake_dollars,
            win_dollars=expected_win,
            decimal_win_amount=decimal_win_amount,
            parlay_name=self.parlay_name,
            doc_num=doc_num,
            delay=delay,
        )

        if not live:
            # Dry-run: stop here, return the would-be payload
            return PlacementResult(
                ticket_number=None,
                dry_run=True,
                accepted_payload=None,
                would_be_payload=insert_body,
                decimal_payout=decimal_payout,
                expected_win=expected_win,
            )

        # 4. insertWagerParlay — actually place
        insert_resp = await self.client.post_json(
            "insertWagerParlay", insert_body
        )
        status = insert_resp.get("STATUS", {})
        if status.get("STATE") != 1 or "DOC" not in status:
            raise PlacementError(
                f"insertWagerParlay rejected: {insert_resp}"
            )
        ticket_number = int(status["DOC"])

        # 5. getPendingByTicket — receipt confirmation
        try:
            await self.client.post_json(
                "getPendingByTicket",
                build_get_pending_by_ticket(
                    agent_id=self.agent_id,
                    customer_id=self.client.customer_id,
                    ticket_number=ticket_number,
                ),
            )
        except Exception:
            # Receipt fetch is non-fatal — the bet landed.
            pass

        return PlacementResult(
            ticket_number=ticket_number,
            dry_run=False,
            accepted_payload=insert_resp,
            would_be_payload=None,
            decimal_payout=decimal_payout,
            expected_win=expected_win,
        )
