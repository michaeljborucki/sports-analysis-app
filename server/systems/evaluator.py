from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from .models import (
    EvaluationGame,
    EvaluationResult,
    SystemEvaluation,
    SystemSignal,
    WagerCandidate,
)
from .context import PLACEMENT_BOOK
from .registry import PRIMARY_SYSTEMS, SUBSET_SYSTEMS, SystemDefinition


# Signals quote Coral33 and nothing else — that is where these bets get
# placed, so the market-best price (which still drives the RULES, via
# context's `*_price` / `*_moneyline` keys) has no business on the page.
# `None` means Coral33 is not offering the selection; the row says so
# rather than substituting a line the user cannot take.
def _placement_price(game: EvaluationGame, key: str) -> int | None:
    return game.context.get(f"{key}_placement")


def _signal(
    definition: SystemDefinition,
    game: EvaluationGame,
    evaluated_at: datetime,
    selection: str,
    reason: str,
    *,
    line: float | int | None = None,
    side: str | None = None,
) -> SystemSignal:
    if definition.bet_type == "moneyline" and side:
        price = _placement_price(game, f"{side}_moneyline")
    elif definition.bet_type == "total":
        direction = "over" if selection.startswith("Over") else "under"
        price = _placement_price(game, f"total_{direction}")
    elif definition.bet_type == "spread":
        spread_side = "home" if selection.startswith(game.home_team) else "away"
        price = _placement_price(game, f"{spread_side}_spread")
    else:
        price = None
    book = PLACEMENT_BOOK if price is not None else None
    return SystemSignal(
        system_id=definition.system_id,
        system_name=definition.name,
        sport=definition.sport,
        event_id=game.event_id,
        home_team=game.home_team,
        away_team=game.away_team,
        commence_time=game.commence_time,
        bet_type=definition.bet_type,  # type: ignore[arg-type]
        selection=selection,
        market_line=line,
        price_american=price,
        book=book,
        qualification_reason=reason,
        data_timestamp=game.data_timestamp,
        evaluated_at=evaluated_at,
    )


def _ml_ok(price: Any) -> bool:
    return isinstance(price, (int, float)) and price < 0


def _price_minus_150_or_better(price: Any) -> bool:
    return isinstance(price, (int, float)) and price >= -150


# ESPN's group id for the ACC, which Football 20 names outright.
_ACC_CONFERENCE_ID = 1


def _g5_non_conference(c: dict[str, Any]) -> bool:
    return (
        c["is_conference_game"] is False
        and c["home_conference_class"] == "g5"
        and c["away_conference_class"] == "g5"
    )


def _between(price: Any, low: int, high: int) -> bool:
    return isinstance(price, (int, float)) and low <= price <= high


def _evaluate_rule(
    d: SystemDefinition, g: EvaluationGame, now: datetime
) -> list[SystemSignal]:
    c = g.context
    sid = d.short_id
    out: list[SystemSignal] = []

    if sid == "Football 1" and c["week"] in (0, 1) and c["home_spread"] <= -36:
        out.append(_signal(d, g, now, f"{g.home_team} {c['home_spread']:+g}", "Week 0/1 home favorite laying at least 36", line=c["home_spread"]))
    elif sid in ("Football 2", "Football 2B") and c["week"] in (0, 1) and c["away_spread"] < 0:
        if sid == "Football 2" or c["away_spread"] <= -14:
            home_line = -c["away_spread"]
            out.append(_signal(d, g, now, f"{g.home_team} {home_line:+g}", "Fade the opening-week road favorite" + (" laying 14+" if sid == "Football 2B" else ""), line=home_line))
    elif sid == "Football 3" and c["week"] in (0, 1):
        for side, opponent in (("home", "away"), ("away", "home")):
            spread = c[f"{side}_spread"]
            if c[f"{side}_conference_class"] == "g5" and c[f"{opponent}_conference_class"] == "p4" and 0 < spread <= 30:
                team = g.home_team if side == "home" else g.away_team
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "G5 underdog receiving 30 or fewer vs Power 4", line=spread))
    elif sid == "Football 4" and c["temperature_f"] > 85 and c["sustained_wind_mph"] < 5:
        out.append(_signal(d, g, now, f"Over {c['total']:g}", "Game-time temperature above 85°F with sustained wind below 5 mph", line=c["total"]))
    elif sid == "Football 5" and min(c["home_spread"], c["away_spread"]) <= -41:
        out.append(_signal(d, g, now, f"Over {c['total']:g}", "A team is favored by at least 41 points", line=c["total"]))
    elif sid == "Football 6" and c["season_type"] == "regular" and c["week"] >= 11 and c["is_divisional"]:
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "NFL divisional game after Week 10", line=c["total"]))
    elif sid == "Football 7":
        for side in ("home", "away"):
            if c[f"{side}_coach"] == "John Harbaugh" and c[f"{side}_spread"] > 0:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "John Harbaugh's active team is an underdog", line=spread))
    elif sid == "Football 9" and c["sustained_wind_mph"] >= 15:
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Sustained game-time wind is at least 15 mph", line=c["total"]))
    elif sid == "Football 10" and c["sustained_wind_mph"] >= 18:
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Sustained game-time wind is at least 18 mph", line=c["total"]))
    elif sid == "Football 12" and c["season_type"] == "regular" and c["week"] == 1 and c["away_spread"] > 0 and not c["away_made_playoffs_previous_season"]:
        out.append(_signal(d, g, now, f"{g.away_team} {c['away_spread']:+g}", "Week 1 road underdog missed the prior playoffs", line=c["away_spread"]))
    elif sid == "Football 14" and c["week"] == 1:
        for side, opponent in (("home", "away"), ("away", "home")):
            if c[f"{side}_games_played"] == 0 and c[f"{opponent}_games_played"] == 1:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(
                    d, g, now, f"{team} {spread:+g}",
                    "Week 1 season-debut team faces an opponent playing its second game",
                    line=spread,
                ))
    elif sid == "Football 15" and c["week"] in (0, 1) and c["total"] <= 48.5 and min(c["home_spread"], c["away_spread"]) <= -4:
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Opening-week total of 48.5 or less with a favorite of 4 or more", line=c["total"]))
    elif sid == "Football 16" and _g5_non_conference(c) and c["home_spread"] < 0:
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Non-conference G5 matchup with a home favorite", line=c["total"]))
    elif sid == "Football 17" and _g5_non_conference(c) and c["home_spread"] >= 0 and c["total"] <= 64:
        out.append(_signal(d, g, now, f"Over {c['total']:g}", "Non-conference G5 matchup with a home underdog or pick, total 64 or less", line=c["total"]))
    elif (
        sid == "Football 18" and c["week"] in (0, 1) and c["neutral_site"]
        and c["is_conference_game"] is False
        and c["home_conference_class"] == "p4" and c["away_conference_class"] == "p4"
    ):
        for side in ("home", "away"):
            spread = c[f"{side}_spread"]
            if -3.5 <= spread < 0 or spread <= -12.5:
                team = g.home_team if side == "home" else g.away_team
                band = "3.5 or less" if spread >= -3.5 else "12.5 or more"
                out.append(_signal(d, g, now, f"{team} {spread:+g}", f"Neutral-site non-conference Power 4 favorite laying {band}", line=spread))
    elif (
        # "Between P4 conference opponents" — SAME conference. VSiN's own
        # match list is the tiebreaker on the ambiguous wording: it holds
        # only the two intra-ACC games and none of the five P4 crossovers,
        # which is also why n is 21 rather than a hundred-plus.
        sid == "Football 19" and c["week"] in (0, 1) and c["is_conference_game"]
        and c["home_conference_class"] == "p4" and c["away_conference_class"] == "p4"
    ):
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Opening-week matchup between two teams from the same Power 4 conference", line=c["total"]))
    elif (
        sid == "Football 20" and c["home_conference_id"] == _ACC_CONFERENCE_ID
        and c["away_conference_id"] == _ACC_CONFERENCE_ID
        and abs(c["home_spread"]) <= 3.5 and c["total"] <= 55.5
    ):
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "ACC matchup inside a field goal with a total of 55.5 or less", line=c["total"]))
    elif sid in ("Football 21", "Football 22"):
        # Fade the big favorite: the bet is the FCS opponent taking the points.
        threshold = -30 if sid == "Football 21" else -24
        for side, opponent in (("home", "away"), ("away", "home")):
            if (
                c[f"{opponent}_is_fbs"] is False
                and c[f"{side}_spread"] <= threshold
                and c[f"{side}_previous_game_played"]
                and c[f"{side}_previous_opponent_is_fbs"]
                and (sid == "Football 21" or c[f"{side}_previous_game_won"] is False)
            ):
                team = g.home_team if opponent == "home" else g.away_team
                spread = c[f"{opponent}_spread"]
                aftermath = "an FBS opponent" if sid == "Football 21" else "an FBS loss"
                out.append(_signal(
                    d, g, now, f"{team} {spread:+g}",
                    f"Fade the {abs(threshold)}+ point favorite laying it on an FCS opponent after {aftermath}",
                    line=spread,
                ))
    elif (
        sid == "Football 23" and c["home_is_fbs"] and c["home_games_played"] == 1
        and c["home_previous_game_played"]
        and c["home_previous_points"] <= 10 and c["home_previous_margin"] <= -17
    ):
        spread = c["away_spread"]
        out.append(_signal(d, g, now, f"{g.away_team} {spread:+g}", "Fade the home team that scored 10 or fewer in a 17+ point opening loss", line=spread))
    elif sid == "Football 24" and c["neutral_site"]:
        for side in ("home", "away"):
            if c[f"{side}_revenge"] and c[f"{side}_spread"] > 0:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "Neutral-site underdog avenging a loss to this opponent", line=spread))
    elif sid == "MLB 1" and _ml_ok(c["away_moneyline"]) and c["home_win_pct"] < .5 and c["away_losing_streak"] >= 3 and c["after_all_star_break"]:
        out.append(_signal(d, g, now, g.away_team, "Road favorite has lost 3+ against a below-.500 opponent after the break", side="away"))
    elif sid == "MLB 2" and _ml_ok(c["away_moneyline"]) and c["away_win_pct"] < .5 and c["away_was_swept_home"] and c["series_game_number"] == 1:
        out.append(_signal(d, g, now, g.away_team, "Below-.500 road favorite opens a series after being swept at home", side="away"))
    elif sid == "MLB 3" and _ml_ok(c["away_moneyline"]) and _price_minus_150_or_better(c["away_moneyline"]) and not c["is_divisional"] and -3 <= c["away_previous_run_margin"] < 0 and c["after_all_star_break"]:
        out.append(_signal(d, g, now, g.away_team, "Non-divisional road favorite -150 or better after a loss by 3 or fewer", side="away"))
    elif sid == "MLB 4" and c["is_divisional"] and 7.5 <= c["total"] <= 8.5:
        for side in ("home", "away"):
            if _ml_ok(c[f"{side}_moneyline"]) and c[f"{side}_win_pct"] < .5:
                team = g.home_team if side == "home" else g.away_team
                out.append(_signal(d, g, now, team, "Below-.500 divisional favorite with total 7.5–8.5", side=side))
    elif sid == "MLB 5" and c["away_moneyline"] > 0 and c["away_win_pct"] > .5 and c["after_all_star_break"] and c["home_first_game_back"]:
        out.append(_signal(d, g, now, g.away_team, "Above-.500 road underdog faces a team returning home after the break", side="away"))
    elif sid == "MLB 6" and 0 < c["away_moneyline"] <= 140 and -2 <= c["away_previous_run_margin"] < 0 and c["series_game_number"] == 2 and 7 <= c["total"] <= 9:
        out.append(_signal(d, g, now, g.away_team, "Road dog +140 or shorter in Game 2 after a loss by 2 or fewer", side="away"))
    elif sid in ("MLB 7", "MLB 12"):
        wanted_day = "Sunday" if sid == "MLB 7" else "Wednesday"
        in_season_window = sid == "MLB 12" or c["month"] in (7, 8)
        if c["day_of_week"] == wanted_day and in_season_window and c["series_game_number"] == 3 and c["series_length"] == 3:
            for side in ("home", "away"):
                if c[f"{side}_series_losses"] == 2 and _between(c[f"{side}_moneyline"], -150, 150):
                    team = g.home_team if side == "home" else g.away_team
                    season_window = " in July/August" if sid == "MLB 7" else ""
                    out.append(_signal(d, g, now, team, f"{wanted_day} three-game-series sweep avoidance{season_window}", side=side))
    elif sid == "MLB 8" and _ml_ok(c["away_moneyline"]) and not c["is_divisional"] and c["total"] <= 10.5 and c["home_win_pct"] < .5 and c["series_game_number"] == 1 and c["away_won_previous_game"]:
        out.append(_signal(d, g, now, g.away_team, "Non-divisional road favorite opens a series vs a below-.500 team after a win", side="away"))
    elif sid == "MLB 9" and c["home_winning_streak"] >= 3 and c["total"] <= 9.5 and c["series_game_number"] == 1 and c["home_previous_game_was_home"]:
        out.append(_signal(d, g, now, g.home_team, "Hot home team stays home for Game 1 of a new series", side="home"))
    elif sid == "MLB 10" and _ml_ok(c["away_moneyline"]) and _price_minus_150_or_better(c["away_moneyline"]) and c["away_previous_runs_scored"] == 0:
        out.append(_signal(d, g, now, g.away_team, "Road favorite -150 or better after a shutout loss", side="away"))
    elif sid == "MLB 11" and not c["is_divisional"] and 7 <= c["total"] <= 9:
        for side in ("home", "away"):
            if _ml_ok(c[f"{side}_moneyline"]) and _price_minus_150_or_better(c[f"{side}_moneyline"]) and c[f"{side}_previous_runs_scored"] >= 10:
                team = g.home_team if side == "home" else g.away_team
                out.append(_signal(d, g, now, team, "Non-divisional favorite -150 or better after scoring 10+ with total 7–9", side=side))
    # --- Systems added 2026-09-10 from the VSiN articles -------------------
    elif sid == "Football 25" and c["home_is_ranked"] and c["away_is_ranked"] and not c["neutral_site"]:
        out.append(_signal(d, g, now, f"{g.home_team} {c['home_spread']:+g}", "Home side in a non-neutral meeting of two ranked teams", line=c["home_spread"]))
    elif (
        sid == "Football 26" and c["home_is_ranked"] and not c["away_is_ranked"]
        and not c["neutral_site"] and abs(c["away_spread"]) <= 7
    ):
        out.append(_signal(d, g, now, f"Under {c['total']:g}", "Unranked road team within a touchdown of a ranked host", line=c["total"]))
    elif sid == "Football 27":
        for side, opponent in (("home", "away"), ("away", "home")):
            allowed = c[f"{opponent}_ppg_allowed"]
            if c[f"{side}_revenge"] and allowed is not None and allowed >= 35:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", f"Avenging a loss to a defense allowing {allowed:.1f} points per game", line=spread))
    elif sid == "Football 28":
        for side in ("home", "away"):
            # Absence is an answer here: a team with no prior outing did not
            # just win 58-9, so it reads as no-match rather than a data gap.
            if not c[f"{side}_previous_game_played"]:
                continue
            scored = c.get(f"{side}_previous_points")
            allowed = c.get(f"{side}_previous_points_allowed")
            if scored is not None and allowed is not None and scored >= 58 and allowed < 10:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", f"Coming off a {scored}-{allowed} demolition", line=spread))
    elif sid == "Football 29" and c["season_type"] == "regular" and c["week"] == 1 and c["is_divisional"] and c["home_spread"] > 0:
        out.append(_signal(d, g, now, f"{g.home_team} {c['home_spread']:+g}", "Week 1 divisional home underdog", line=c["home_spread"]))
    elif (
        sid == "Football 30" and c["season_type"] == "regular" and c["week"] == 1
        and c["is_conference_game"] is False and -3 <= c["home_spread"] <= 3
    ):
        spread = c["away_spread"]
        out.append(_signal(d, g, now, f"{g.away_team} {spread:+g}", "Fade the Week 1 non-conference home team priced inside a field goal", line=spread))
    elif (
        sid == "Football 31" and c["season_type"] == "regular" and c["week"] == 1
        and 4 <= c["away_prior_season_wins"] <= 6
    ):
        spread = c["away_spread"]
        out.append(_signal(d, g, now, f"{g.away_team} {spread:+g}", f"Week 1 road team off a {c['away_prior_season_wins']}-win season", line=spread))
    elif sid == "Football 32" and c["season_type"] == "regular" and c["week"] == 1:
        for side in ("home", "away"):
            if c[f"{side}_spread"] >= 6.5:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "Week 1 underdog receiving 6.5 or more", line=spread))
    elif (
        sid == "Football 33" and c["season_type"] == "regular" and c["week"] == 1
        and c["home_spread"] < 0 and c["away_prior_season_win_pct"] > 0.5
    ):
        out.append(_signal(d, g, now, f"{g.home_team} {c['home_spread']:+g}", "Week 1 home favorite hosting a team that finished above .500", line=c["home_spread"]))
    elif (
        sid == "Football 34" and c["season_type"] == "regular" and c["week"] == 1
        and c["is_divisional"] and 0 < c["away_spread"] <= 6.5
    ):
        spread = c["away_spread"]
        out.append(_signal(d, g, now, f"{g.away_team} {spread:+g}", "Week 1 divisional road underdog inside a touchdown", line=spread))
    elif sid == "Football 35" and c["season_type"] == "regular" and c["week"] == 1:
        # "when not matched up against a fellow high-scoring team" -- two
        # such offenses cancel the angle rather than firing it twice.
        for side, opponent in (("home", "away"), ("away", "home")):
            if c[f"{side}_prior_season_ppg"] > 26 and c[f"{opponent}_prior_season_ppg"] <= 26:
                team = g.home_team if opponent == "home" else g.away_team
                spread = c[f"{opponent}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "Fade the team that averaged better than 26 points last season", line=spread))
    elif sid == "Football 36" and c["season_type"] == "regular" and c["week"] == 1:
        for side, opponent in (("home", "away"), ("away", "home")):
            if c[f"{side}_prior_season_ppg_allowed"] < 20 <= c[f"{opponent}_prior_season_ppg_allowed"]:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", "Back the team that allowed under 20 points per game last season", line=spread))
    elif sid == "Football 37" and c["season_type"] == "regular" and c["week"] == 1:
        for side, opponent in (("home", "away"), ("away", "home")):
            if c[f"{side}_prior_season_close_losses"] >= 8 > c[f"{opponent}_prior_season_close_losses"]:
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", f"Rebound off {c[f'{side}_prior_season_close_losses']} losses by 8 or fewer last season", line=spread))
    elif sid in ("Football 38", "Football 39") and c["season_type"] == "regular" and c["week"] == 1:
        for side, opponent in (("home", "away"), ("away", "home")):
            if c[f"{side}_prior_season_win_change"] <= -5 < c[f"{opponent}_prior_season_win_change"]:
                if sid == "Football 39":
                    out.append(_signal(d, g, now, f"Under {c['total']:g}", "Week 1 game involving a team that shed 5 or more wins last season", line=c["total"]))
                    break
                team = g.home_team if side == "home" else g.away_team
                spread = c[f"{side}_spread"]
                out.append(_signal(d, g, now, f"{team} {spread:+g}", f"Rebound after dropping {abs(c[f'{side}_prior_season_win_change'])} wins last season", line=spread))
    elif (
        sid == "MLB 13" and c["month"] >= 8
        and c["home_win_pct"] >= 0.580 and c["away_win_pct"] >= 0.580
    ):
        for side in ("home", "away"):
            if _between(c[f"{side}_moneyline"], -175, -111):
                team = g.home_team if side == "home" else g.away_team
                out.append(_signal(d, g, now, team, "August-or-later meeting of two .580 teams, backing the short favorite", side=side))
    elif sid == "MLB 14" and c["series_game_number"] == c["series_length"]:
        for side in ("home", "away"):
            if c[f"{side}_losing_streak"] >= 3:
                team = g.home_team if side == "home" else g.away_team
                out.append(_signal(d, g, now, team, f"Wrapping up a series on a {c[f'{side}_losing_streak']}-game losing streak", side=side))
    elif (
        sid == "MLB 15" and c["series_game_number"] == c["series_length"]
        and 101 <= c["away_moneyline"] <= 187 and c["away_ends_road_trip"]
    ):
        out.append(_signal(d, g, now, g.away_team, "Road underdog in a series finale that ends a road trip", side="away"))
    return out


def evaluate_systems(
    games: list[EvaluationGame], *, evaluated_at: datetime, requested_date: date
) -> EvaluationResult:
    upcoming = [g for g in games if g.commence_time > evaluated_at]
    signals: list[SystemSignal] = []
    evaluations: list[SystemEvaluation] = []
    for d in PRIMARY_SYSTEMS:
        if not d.enabled:
            evaluations.append(SystemEvaluation(system_id=d.system_id, short_id=d.short_id, system_name=d.name, sport=d.sport, bet_type=d.bet_type, source_claim=d.source_claim, rule_status=d.rule_status, status="disabled"))
            continue
        sport_games = [g for g in upcoming if g.sport == d.sport]
        missing: set[str] = set()
        matches: list[SystemSignal] = []
        evaluated = 0
        skipped = 0
        for g in sport_games:
            # Deliberate exclusions, not coverage gaps: an FCS game or a domed
            # stadium is outside the rule's universe, so it counts as neither
            # evaluated nor skipped.
            if (
                d.sport == "ncaaf" and d.fbs_only
                and g.context.get("is_fbs_game") is False
            ):
                continue
            if d.short_id in ("Football 4", "Football 9", "Football 10") and g.context.get("weather_applicable") is False:
                continue
            absent = {field for field in d.required_fields if g.context.get(field) is None}
            if absent:
                missing.update(absent)
                skipped += 1
                continue
            evaluated += 1
            matches.extend(_evaluate_rule(d, g, evaluated_at))
        signals.extend(matches)
        # Coverage decides the verdict. One game with a hole must not mask a
        # real answer drawn from the rest of the slate — a rule that judged
        # any game has an answer, and "unable to evaluate" is reserved for
        # zero coverage. An empty or wholly-excluded slate is a calendar
        # fact ("no NFL games today"), not a data failure.
        if matches:
            status = "qualified"
        elif evaluated:
            status = "no_match"
        elif skipped:
            status = "unable_to_evaluate"
        elif sport_games:
            # Every game was deliberately excluded (all-FCS slate, all domes).
            # We had enough data to rule them out, so this is a confirmed
            # non-answer, not an empty calendar.
            status = "no_match"
        else:
            status = "no_slate"
            missing.clear()
        evaluations.append(SystemEvaluation(system_id=d.system_id, short_id=d.short_id, system_name=d.name, sport=d.sport, bet_type=d.bet_type, source_claim=d.source_claim, rule_status=d.rule_status, status=status, match_count=len(matches), evaluated_games=evaluated, skipped_games=skipped, missing_fields=sorted(missing)))

    parent = next(d for d in PRIMARY_SYSTEMS if d.short_id == "Football 2")
    if any(s.system_id == parent.system_id for s in signals):
        subset = SUBSET_SYSTEMS[0]
        for g in upcoming:
            if g.sport == "ncaaf" and all(g.context.get(f) is not None for f in subset.required_fields):
                signals.extend(_evaluate_rule(subset, g, evaluated_at))
    return EvaluationResult(evaluations=evaluations, signals=signals)


def deduplicate_wagers(signals: list[SystemSignal]) -> list[WagerCandidate]:
    grouped: dict[tuple, list[SystemSignal]] = defaultdict(list)
    for signal in signals:
        key = (signal.event_id, signal.bet_type, signal.selection, signal.market_line, signal.price_american, signal.book)
        grouped[key].append(signal)
    wagers: list[WagerCandidate] = []
    for items in grouped.values():
        first = items[0]
        ordered = sorted(
            items,
            key=lambda item: ("FOOTBALL_2B_" in item.system_id, item.system_id),
        )
        wagers.append(WagerCandidate(
            sport=first.sport, event_id=first.event_id, home_team=first.home_team,
            away_team=first.away_team, commence_time=first.commence_time,
            bet_type=first.bet_type, selection=first.selection,
            market_line=first.market_line, price_american=first.price_american,
            book=first.book,
            qualification_reason="; ".join(dict.fromkeys(i.qualification_reason for i in ordered)),
            data_timestamp=first.data_timestamp,
            supporting_system_ids=[i.system_id for i in ordered],
            supporting_system_names=[i.system_name for i in ordered],
        ))
    return sorted(wagers, key=lambda w: (w.commence_time, w.event_id, w.selection))
