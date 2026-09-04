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
            if d.sport == "ncaaf" and g.context.get("is_fbs_game") is False:
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
