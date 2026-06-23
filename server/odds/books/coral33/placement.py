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

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from server.sidecar.models import LegSpec


logger = logging.getLogger(__name__)


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
    """Orchestrates the five-call open-spot parlay placement chain.

    Self-healing LegSpec: if the incoming leg is missing Coral-side
    fields (game_num, rot_num, sport_type, …), the placer fetches them
    just-in-time via Get_LeagueLines2 before running the five-call
    chain. See _lookup_coral_context."""

    LIVE_ENV_VAR = "CORAL33_PLACEMENT_LIVE"

    # Maps the cache's sport_key (e.g. "mlb") to Coral33's
    # (sport_type, [sport_sub_types]) for the parlay tab.
    # Mirrors server/config/coral33.toml's [sports.<key>] entries.
    # Sub-types are tried in order; first match wins.
    SPORT_KEY_TO_CORAL: dict[str, tuple[str, list[str]]] = {
        "mlb":            ("BASEBALL",   ["MLB"]),
        "baseball_ncaa":  ("BASEBALL",   ["NCAABASEBALL"]),
        "asian_baseball": ("BASEBALL",   ["KBO", "NPB"]),
        "nba":            ("BASKETBALL", ["NBA"]),
        "wnba":           ("BASKETBALL", ["WNBA"]),
        "nhl":            ("HOCKEY",     ["NHL"]),
        "soccer":         ("SOCCER",     ["WORLD CUP", "PREMIER LEAGUE", "CHAMPIONS LEAGUE", "EUROPA"]),
        "tennis":         ("TENNIS",     ["WTA MATCHUPS", "ATP MATCHUPS"]),
        "boxing":         ("BOXING",     ["BOXING"]),
        "ufc":            ("BOXING",     ["UFC"]),
        "cricket":        ("CRICKET",    ["CRICKET"]),
    }

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
        # Cache Get_LeagueLines2 responses for ~60s keyed by
        # (sport_type, sport_sub_type, period). Repeat placements on the
        # same sport within the window reuse the line catalog instead of
        # re-hitting Coral33.
        self._lines_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}
        self._LINES_TTL_SECONDS = 60.0

    async def _fetch_lines(
        self,
        sport_type: str,
        sport_sub_type: str,
        period: str = "Game",
    ) -> dict:
        """Get_LeagueLines2 against the Parlay tab, cached for 60s.

        Returns the raw response; caller picks the matching game from
        response['Lines']. Uses post_form because the existing Coral33
        client only has form-encoded Get_LeagueLines2 wiring; the
        placement chain itself still uses post_json."""
        key = (sport_type, sport_sub_type, period)
        now = time.monotonic()
        if key in self._lines_cache:
            cached_at, payload = self._lines_cache[key]
            if now - cached_at < self._LINES_TTL_SECONDS:
                return payload
        resp = await self.client.post_form("Get_LeagueLines2", {
            "sportType": sport_type,
            "sportSubType": sport_sub_type,
            "period": period,
            "hourFilter": 0,
            "propDescription": "Game",
            "wagerType": "Parlay",
            "keyword": "",
            "correlationID": "",
            "periodNumber": 0,
            "grouping": "",
            "periods": 0,
            "rotOrder": 0,
            "placeLateFlag": False,
            "RRO": 1,
        })
        self._lines_cache[key] = (now, resp)
        return resp

    @staticmethod
    def _team_match(team_field: str, target: str) -> bool:
        """Loose match between Coral33's TeamID and our cache's team name.

        Coral pads / sometimes shortens names. We strip both sides and
        check containment in either direction to handle e.g.
        ``"Kansas City Royals"`` vs Coral's ``"Royals"`` or
        ``"Chicago Cubs    "`` vs ``"Chicago Cubs"``."""
        a = (team_field or "").strip().lower()
        b = (target or "").strip().lower()
        if not a or not b:
            return False
        return a == b or a in b or b in a

    @staticmethod
    def _determine_side(
        match_game: dict,
        target_team: str,
        ev_leg: LegSpec,
    ) -> int | None:
        """Which side of the matched Coral game are we betting on?
        Returns 1 (Team1) or 2 (Team2), or None if undeterminable.

        For moneylines + spreads, the target is a team name; we match by
        team. For totals, the target is 'Over' or 'Under' — there's no
        team to match, so we map to side=1 for Over and side=2 for
        Under (Coral's convention: TtlPtsAdj1 = Over, TtlPtsAdj2 = Under,
        confirmed in HAR fixture)."""
        if ev_leg.line_type == "T":
            ot = (target_team or "").strip().lower()
            if ot == "over":
                return 1
            if ot == "under":
                return 2
            return None
        # M or S: identify by team name
        if Coral33Placer._team_match(
            match_game.get("Team1ID", ""), target_team,
        ):
            return 1
        if Coral33Placer._team_match(
            match_game.get("Team2ID", ""), target_team,
        ):
            return 2
        return None

    @staticmethod
    def _extract_price_fields(
        match_game: dict,
        side: int,                # 1 or 2
        ev_leg: LegSpec,
    ) -> dict:
        """Pull the price + point fields appropriate to ev_leg.line_type
        from the matched Coral game. Returns a dict the caller splats into
        the LegSpec via dataclasses.replace."""
        # Team identification — Team1 / Team2 fields exist in all three
        # market types since Coral keys everything off rotation numbers.
        team_id = (match_game.get(f"Team{side}ID") or "").strip()
        rot_num = match_game.get(f"Team{side}RotNum", 0)

        line_type = ev_leg.line_type
        if line_type == "M":
            return {
                "chosen_team_id": team_id,
                "rot_num": rot_num,
                "price_american": match_game.get(f"MoneyLine{side}", 0),
                "price_decimal":  match_game.get(f"MoneyLineDecimal{side}", 0.0),
                "price_numerator":  match_game.get(f"MoneyLineNumerator{side}", 0),
                "price_denominator": match_game.get(f"MoneyLineDenominator{side}", 0),
                "spread": 0.0,
                "total_points": 0.0,
            }
        if line_type == "S":
            # Coral's `Spread` field is signed from Team1's perspective.
            # Team1 spread = +Spread; Team2 spread = -Spread.
            spread_team1 = match_game.get("Spread") or 0.0
            spread = float(spread_team1) if side == 1 else -float(spread_team1)
            return {
                "chosen_team_id": team_id,
                "rot_num": rot_num,
                "price_american": match_game.get(f"SpreadAdj{side}", 0),
                "price_decimal":  match_game.get(f"SpreadDecimal{side}", 0.0),
                "price_numerator":  match_game.get(f"SpreadNumerator{side}", 0),
                "price_denominator": match_game.get(f"SpreadDenominator{side}", 0),
                "spread": spread,
                "total_points": 0.0,
            }
        # line_type == "T" — totals (Over / Under)
        # Coral's convention: TtlPtsAdj1 = Over, TtlPtsAdj2 = Under.
        # The "chosen_team_id" for a total is literally "Over"/"Under";
        # we use rot_num from the corresponding side (rot1 / rot2).
        return {
            "chosen_team_id": "Over" if side == 1 else "Under",
            "rot_num": rot_num,
            "price_american": match_game.get(f"TtlPtsAdj{side}", 0),
            "price_decimal":  match_game.get(f"TtlPointsDecimal{side}", 0.0),
            "price_numerator":  match_game.get(f"TtlPointsNumerator{side}", 0),
            "price_denominator": match_game.get(f"TtlPointsDenominator{side}", 0),
            "spread": 0.0,
            "total_points": float(match_game.get("TotalPoints") or 0.0),
        }

    async def _lookup_coral_context(
        self,
        ev_leg: LegSpec,
    ) -> LegSpec:
        """If ``ev_leg`` is missing Coral-side fields (game_num, sport_type,
        rot_num, …), populate them via Get_LeagueLines2 and return an
        enriched LegSpec. Otherwise return the input unchanged.

        Handles all three line types — moneyline (M), spread (S), and
        total (T) — each pulling its specific price/point fields from
        Coral's response."""
        from dataclasses import replace
        if ev_leg.game_num > 0 and ev_leg.sport_type and ev_leg.rot_num > 0:
            return ev_leg   # already populated, no lookup needed

        if ev_leg.line_type not in ("M", "S", "T"):
            raise PlacementError(
                f"unsupported line_type={ev_leg.line_type!r}; "
                f"expected one of 'M' (moneyline), 'S' (spread), 'T' (total)"
            )

        coral_mapping = self.SPORT_KEY_TO_CORAL.get(ev_leg.sport_key)
        if coral_mapping is None:
            raise PlacementError(
                f"no Coral sport-type mapping for sport_key={ev_leg.sport_key!r}; "
                f"add to Coral33Placer.SPORT_KEY_TO_CORAL"
            )
        sport_type, sub_types = coral_mapping

        # Try each candidate sub-type until we find a matching game.
        for sub_type in sub_types:
            t0 = time.monotonic()
            try:
                lines_resp = await self._fetch_lines(
                    sport_type, sub_type, "Game",
                )
            except Exception as ex:
                logger.warning(
                    "[placer %s] Get_LeagueLines2 %s/%s failed: %s",
                    self.client.customer_id, sport_type, sub_type, ex,
                )
                continue
            games = lines_resp.get("Lines") or []
            logger.info(
                "[placer %s] Get_LeagueLines2 %s/%s → %d games  %.0fms",
                self.client.customer_id, sport_type, sub_type, len(games),
                (time.monotonic() - t0) * 1000,
            )

            # Find the game by home + away team.
            target_home = ev_leg.home_team
            target_away = ev_leg.away_team
            target_team = ev_leg.outcome_name  # who we bet on
            match_game = None
            for g in games:
                t1 = g.get("Team1ID", "") or ""
                t2 = g.get("Team2ID", "") or ""
                # In Coral, Team1 = away, Team2 = home (confirmed from HAR).
                if (
                    (self._team_match(t1, target_away)
                     or self._team_match(t1, target_home))
                    and
                    (self._team_match(t2, target_home)
                     or self._team_match(t2, target_away))
                ):
                    match_game = g
                    break
            if match_game is None:
                continue   # try next sub_type

            # Determine which side is ours (Team1 vs Team2) then extract
            # the line-type-specific price + point fields.
            side = self._determine_side(match_game, target_team, ev_leg)
            if side is None:
                raise PlacementError(
                    f"found game {match_game.get('Team1ID')!r} vs "
                    f"{match_game.get('Team2ID')!r} but couldn't determine "
                    f"the side for line_type={ev_leg.line_type!r} "
                    f"target={target_team!r}"
                )

            extra_fields = self._extract_price_fields(
                match_game, side, ev_leg,
            )
            chosen_team_id = extra_fields["chosen_team_id"]
            rot_num = extra_fields["rot_num"]
            price_american = extra_fields["price_american"]

            # Line-moved check: refuse to place if the spread/total Coral
            # currently offers differs from what the EV row captured. Better
            # to fail loudly than to silently place an inverted bet (e.g.
            # user picked "Reds -1.5" but Coral now shows "Reds +1.5" —
            # those are totally different bets at totally different prices).
            if ev_leg.line_type == "S":
                coral_spread = float(extra_fields["spread"])
                if abs(coral_spread - float(ev_leg.spread)) > 0.01:
                    raise PlacementError(
                        f"line moved: requested spread {ev_leg.spread:+g} for "
                        f"{chosen_team_id} but Coral now offers "
                        f"{coral_spread:+g}. Refresh the EV row and re-fire."
                    )
            elif ev_leg.line_type == "T":
                coral_total = float(extra_fields["total_points"])
                if abs(coral_total - float(ev_leg.total_points)) > 0.01:
                    raise PlacementError(
                        f"line moved: requested total {ev_leg.total_points:g} "
                        f"({chosen_team_id}) but Coral now offers "
                        f"{coral_total:g}. Refresh the EV row and re-fire."
                    )

            logger.info(
                "[placer %s] self-heal MATCH game_num=%d %s "
                "line_type=%s @ %+d  (sub_type=%s)",
                self.client.customer_id, match_game.get("GameNum", 0),
                chosen_team_id, ev_leg.line_type, price_american, sub_type,
            )

            # Build the description in Coral's canonical form. The
            # point-suffix differs by line type — included between the
            # team and the price for spreads/totals so it matches Coral's
            # HAR-captured format.
            desc_point = ""
            if ev_leg.line_type == "S":
                desc_point = f" {extra_fields['spread']:+g}"
            elif ev_leg.line_type == "T":
                # Coral renders e.g. "Over 8.5" or "Under 8.5"
                desc_point = f" {extra_fields['total_points']:g}"

            return replace(
                ev_leg,
                sport_type=match_game.get("SportType",
                                          sport_type.ljust(20)),
                sport_sub_type=match_game.get("SportSubType",
                                              sub_type.ljust(12)),
                period="Game",
                game_num=int(match_game.get("GameNum", 0)),
                chosen_team_id=chosen_team_id,
                rot_num=int(rot_num),
                price_american=int(price_american),
                price_decimal=float(extra_fields["price_decimal"]),
                price_numerator=int(extra_fields["price_numerator"]),
                price_denominator=int(extra_fields["price_denominator"]),
                spread=float(extra_fields.get("spread", ev_leg.spread)),
                total_points=float(
                    extra_fields.get("total_points", ev_leg.total_points)
                ),
                game_datetime=match_game.get("GameDateTime", ""),
                description=(
                    f"{sport_type.capitalize()} #{rot_num} "
                    f"{chosen_team_id}{desc_point} "
                    f"{price_american:+d} - For Game "
                ),
            )

        # No sub_type produced a match.
        raise PlacementError(
            f"could not find game {ev_leg.away_team!r} @ "
            f"{ev_leg.home_team!r} in Coral33 Parlay tab for "
            f"sport_key={ev_leg.sport_key!r} (tried {sub_types}). "
            f"Line may have closed or sport mapping is wrong."
        )

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

        t_start = time.monotonic()
        cust = self.client.customer_id
        logger.info(
            "[placer %s] place_open_parlay START "
            "leg=%s %+d (decimal=%.3f) stake=$%.2f mode=%s",
            cust, ev_leg.chosen_team_id or ev_leg.outcome_name,
            ev_leg.price_american,
            ev_leg.price_decimal, stake_dollars,
            "live" if live else "dry-run",
        )

        # Self-heal: if resolve.py couldn't populate Coral-side fields
        # (sport_type, game_num, rot_num), look them up via
        # Get_LeagueLines2 now. No-op if the leg is already complete.
        t_heal = time.monotonic()
        ev_leg = await self._lookup_coral_context(ev_leg)
        heal_ms = (time.monotonic() - t_heal) * 1000
        if heal_ms > 5:  # log only when we actually did a lookup
            logger.info(
                "[placer %s] (0) self-heal LegSpec %.0fms",
                cust, heal_ms,
            )

        # 1. getParlaySpecs (cached per Placer instance)
        if self._specs_cache is None:
            t0 = time.monotonic()
            self._specs_cache = await self.client.post_json(
                "getParlaySpecs",
                build_get_parlay_specs(cust, self.parlay_name),
            )
            logger.info(
                "[placer %s] (1) getParlaySpecs OK  %.0fms",
                cust, (time.monotonic() - t0) * 1000,
            )
        else:
            logger.info("[placer %s] (1) getParlaySpecs CACHED", cust)

        # 2 + 3. getInfoParlay AND checkWagerLineMulti in PARALLEL.
        # They're independent: getInfoParlay returns the parlay-card
        # payout multiplier, checkWagerLineMulti returns the current line
        # snapshot + DELAY.sig. Running them concurrently saves one full
        # network round-trip (typically 200-400ms via residential proxy).
        selects = f"{ev_leg.game_num}-{ev_leg.line_type}|{ev_leg.chosen_team_id}^0"
        position = int(time.time() * 1000) % 10**8

        t_par = time.monotonic()
        info, check = await asyncio.gather(
            self.client.post_json(
                "getInfoParlay",
                build_get_info_parlay(
                    customer_id=cust,
                    parlay_name=self.parlay_name,
                    teams=2,
                    selects=selects,
                ),
            ),
            self.client.post_json(
                "checkWagerLineMulti",
                build_check_wager_line_multi_parlay(
                    customer_id=cust,
                    leg=ev_leg,
                    position=position,
                    risk_dollars=stake_dollars,
                    # win_dollars is filled in below after we have the
                    # multiplier — but checkWagerLineMulti only validates
                    # against risk; the win field is informational. Pass
                    # the placed-leg win as a conservative estimate.
                    win_dollars=ev_leg.price_decimal * stake_dollars - stake_dollars,
                ),
            ),
        )
        logger.info(
            "[placer %s] (2+3) getInfoParlay+checkWagerLineMulti PARALLEL %.0fms",
            cust, (time.monotonic() - t_par) * 1000,
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
            logger.info(
                "[placer %s] DRY-RUN halt; total %.0fms (would-be ticket on $%.2f, win=$%.2f)",
                cust, (time.monotonic() - t_start) * 1000,
                stake_dollars, expected_win,
            )
            return PlacementResult(
                ticket_number=None,
                dry_run=True,
                accepted_payload=None,
                would_be_payload=insert_body,
                decimal_payout=decimal_payout,
                expected_win=expected_win,
            )

        # 4. insertWagerParlay — actually place
        t4 = time.monotonic()
        insert_resp = await self.client.post_json(
            "insertWagerParlay", insert_body
        )
        status = insert_resp.get("STATUS", {})
        if status.get("STATE") != 1 or "DOC" not in status:
            logger.error(
                "[placer %s] (4) insertWagerParlay REJECTED %.0fms — response=%s",
                cust, (time.monotonic() - t4) * 1000, insert_resp,
            )
            raise PlacementError(
                f"insertWagerParlay rejected: {insert_resp}"
            )
        ticket_number = int(status["DOC"])
        logger.info(
            "[placer %s] (4) insertWagerParlay PLACED %.0fms ticket=#%d win=$%.2f stake=$%.2f",
            cust, (time.monotonic() - t4) * 1000,
            ticket_number, expected_win, stake_dollars,
        )

        # 5. getPendingByTicket — fire-and-forget receipt confirmation.
        # We already have the ticket # from insertWagerParlay; the receipt
        # call is just for the audit's accepted_payload. Don't block the
        # response on it — schedule and let it run in the background.
        async def _fire_receipt_poll():
            try:
                await self.client.post_json(
                    "getPendingByTicket",
                    build_get_pending_by_ticket(
                        agent_id=self.agent_id,
                        customer_id=cust,
                        ticket_number=ticket_number,
                    ),
                )
                logger.debug(
                    "[placer %s] (5) getPendingByTicket OK for ticket=#%d",
                    cust, ticket_number,
                )
            except Exception as ex:
                logger.debug(
                    "[placer %s] (5) getPendingByTicket failed (non-fatal): %s",
                    cust, ex,
                )
        asyncio.create_task(_fire_receipt_poll())

        logger.info(
            "[placer %s] place_open_parlay DONE total %.0fms ticket=#%d",
            cust, (time.monotonic() - t_start) * 1000, ticket_number,
        )

        return PlacementResult(
            ticket_number=ticket_number,
            dry_run=False,
            accepted_payload=insert_resp,
            would_be_payload=None,
            decimal_payout=decimal_payout,
            expected_win=expected_win,
        )
