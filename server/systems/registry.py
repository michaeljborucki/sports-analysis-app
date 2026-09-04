from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Sport = Literal["mlb", "ncaaf", "nfl"]
BetType = Literal["moneyline", "spread", "total", "tbd"]


@dataclass(frozen=True)
class SystemDefinition:
    system_id: str
    short_id: str
    name: str
    sport: Sport
    bet_type: BetType
    source_claim: str
    required_fields: tuple[str, ...] = ()
    enabled: bool = True
    rule_status: Literal["captured", "requires_verification", "incomplete_tbd"] = "captured"
    parent_system_id: str | None = None
    verified_backtest: dict | None = None


def _s(
    short_id: str,
    slug: str,
    name: str,
    sport: Sport,
    bet_type: BetType,
    claim: str,
    required: tuple[str, ...] = (),
    *,
    enabled: bool = True,
    status: Literal["captured", "requires_verification", "incomplete_tbd"] = "captured",
    parent: str | None = None,
) -> SystemDefinition:
    if sport == "ncaaf" and enabled and "is_fbs_game" not in required:
        required = ("is_fbs_game", *required)
    return SystemDefinition(
        system_id=slug,
        short_id=short_id,
        name=name,
        sport=sport,
        bet_type=bet_type,
        source_claim=claim,
        required_fields=required,
        enabled=enabled,
        rule_status=status,
        parent_system_id=parent,
    )


PRIMARY_SYSTEMS: tuple[SystemDefinition, ...] = (
    _s("Football 1", "FOOTBALL_1_CFB_MASSIVE_HOME_FAVORITE", "Massive Week 0/1 Home Favorite", "ncaaf", "spread", "18-5 ATS (78.3%) since 2013", ("week", "home_spread")),
    _s("Football 2", "FOOTBALL_2_CFB_ROAD_FAVORITE_FADE", "Week 0/1 Road-Favorite Fade", "ncaaf", "spread", "Road favorites: 45-66-2 ATS since 2013", ("week", "away_spread")),
    _s("Football 3", "FOOTBALL_3_CFB_G5_DOG_VS_P4", "G5 Underdog vs Power 4", "ncaaf", "spread", "29-17 ATS since 2023", ("week", "home_conference_class", "away_conference_class", "home_spread", "away_spread")),
    _s("Football 4", "FOOTBALL_4_CFB_HOT_LOW_WIND_OVER", "Hot / Low-Wind Over", "ncaaf", "total", "Record/ROI not preserved", ("weather_applicable", "temperature_f", "sustained_wind_mph", "total")),
    _s("Football 5", "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER", "41+ Point Favorite Over", "ncaaf", "total", "43-23 at publication", ("home_spread", "away_spread", "total")),
    _s("Football 6", "FOOTBALL_6_NFL_LATE_DIVISIONAL_UNDER", "Late-Season NFL Divisional Under", "nfl", "total", "61% since 2005", ("season_type", "week", "is_divisional", "total")),
    _s("Football 7", "FOOTBALL_7_NFL_HARBAUGH_UNDERDOG_ATS", "John Harbaugh Underdog", "nfl", "spread", "16-7 ATS at publication", ("home_coach", "away_coach", "home_spread", "away_spread")),
    _s("Football 8", "FOOTBALL_8_CFB_MAC_BOWL_FADE_TBD", "MAC Bowl Fade", "ncaaf", "tbd", "MAC teams 48-79 (37%) straight-up in bowls", enabled=False, status="incomplete_tbd"),
    _s("Football 9", "FOOTBALL_9_CFB_WIND_15_PLUS_UNDER", "15+ MPH Wind Under", "ncaaf", "total", "52-35, +13.5 units for one season", ("weather_applicable", "sustained_wind_mph", "total")),
    _s("Football 10", "FOOTBALL_10_CFB_WIND_18_PLUS_UNDER", "18+ MPH Wind Under", "ncaaf", "total", "Decade-long trend; exact record not preserved", ("weather_applicable", "sustained_wind_mph", "total")),
    _s("Football 11", "FOOTBALL_11_NFL_EARLY_DIVISIONAL_DOG_TBD", "Early Divisional Underdog", "nfl", "tbd", "121-130-2 (48.2%)", enabled=False, status="incomplete_tbd"),
    _s("Football 12", "FOOTBALL_12_NFL_WEEK1_ROAD_DOG_NO_PLAYOFFS", "Week 1 Road Dog, Missed Playoffs", "nfl", "spread", "73-46-4 ATS (61.3%)", ("season_type", "week", "away_spread", "away_made_playoffs_previous_season")),
    _s("Football 13", "FOOTBALL_13_NFL_OVER_AFTER_BOTH_UNDER", "Early Over After Both Teams Went Under", "nfl", "total", "121-81-1 (59.9%)", enabled=False, status="requires_verification"),
    _s("Football 14", "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE", "Week 1 Rest/Experience Advantage", "ncaaf", "spread", "62-39 ATS (61.6%)", ("week", "home_games_played", "away_games_played", "home_spread", "away_spread")),
    _s("MLB 1", "MLB_1_COLD_ROAD_FAVORITE_VS_BELOW_500", "Cold Road Favorite vs Below-.500 Team", "mlb", "moneyline", "87-31 (74%), 27.3% ROI", ("away_moneyline", "away_losing_streak", "home_win_pct", "after_all_star_break")),
    _s("MLB 2", "MLB_2_ROAD_FAVORITE_OFF_HOME_SWEEP", "Road Favorite Off Home Sweep", "mlb", "moneyline", "43-13 (77%), 34% ROI", ("away_moneyline", "away_win_pct", "away_was_swept_home", "series_game_number")),
    _s("MLB 3", "MLB_3_NONDIV_ROAD_FAVORITE_AFTER_CLOSE_LOSS", "Non-Divisional Road Favorite After Close Loss", "mlb", "moneyline", "117-71 (62%), 10.6% ROI", ("away_moneyline", "is_divisional", "away_previous_run_margin", "after_all_star_break")),
    _s("MLB 4", "MLB_4_DIVISIONAL_FAVORITE_BELOW_500", "Divisional Favorite Below .500", "mlb", "moneyline", "Approximately 67%, 13.4% ROI", ("home_moneyline", "away_moneyline", "home_win_pct", "away_win_pct", "is_divisional", "total")),
    _s("MLB 5", "MLB_5_ROAD_DOG_ABOVE_500_VS_RETURNING_HOME", "Road Dog Above .500 vs Returning-Home Team", "mlb", "moneyline", "90-52 (63.6%), 38.9% ROI", ("away_moneyline", "away_win_pct", "after_all_star_break", "home_first_game_back")),
    _s("MLB 6", "MLB_6_ROAD_DOG_CLOSE_LOSS_GAME2", "Road Dog Off Close Loss — Game 2", "mlb", "moneyline", "98-92 (52%), 14% ROI", ("away_moneyline", "away_previous_run_margin", "series_game_number", "total")),
    _s("MLB 7", "MLB_7_SWEEP_SUNDAY", "Sweep Sunday", "mlb", "moneyline", "164-130 (56%), 15% ROI", ("day_of_week", "month", "series_game_number", "series_length", "home_series_losses", "away_series_losses", "home_moneyline", "away_moneyline")),
    _s("MLB 8", "MLB_8_NONDIV_ROAD_FAVORITE_VS_BELOW_500", "Non-Divisional Road Favorite vs Below-.500 Team", "mlb", "moneyline", "184-96 (66%), 16% ROI", ("away_moneyline", "is_divisional", "total", "home_win_pct", "series_game_number", "away_won_previous_game")),
    _s("MLB 9", "MLB_9_HOT_TEAM_STAYING_HOME_NEW_SERIES", "Hot Team Staying Home for New Series", "mlb", "moneyline", "308-194 (61.4%), 7.2% ROI", ("home_winning_streak", "total", "series_game_number", "home_previous_game_was_home", "home_moneyline")),
    _s("MLB 10", "MLB_10_ROAD_FAVORITE_AFTER_SHUTOUT_LOSS", "Road Favorite After Shutout Loss", "mlb", "moneyline", "113-52 (69%), 22% ROI", ("away_moneyline", "away_previous_runs_scored")),
    _s("MLB 11", "MLB_11_FAVORITE_AFTER_10_PLUS_RUNS", "Favorite After Scoring 10+ Runs", "mlb", "moneyline", "155-93 (63%), 13.5% ROI", ("home_moneyline", "away_moneyline", "is_divisional", "total", "home_previous_runs_scored", "away_previous_runs_scored")),
    _s("MLB 12", "MLB_12_SWEEP_WEDNESDAY", "Sweep Wednesday", "mlb", "moneyline", "82-63 (57%), 18% ROI", ("day_of_week", "series_game_number", "series_length", "home_series_losses", "away_series_losses", "home_moneyline", "away_moneyline")),
)

SUBSET_SYSTEMS: tuple[SystemDefinition, ...] = (
    _s(
        "Football 2B",
        "FOOTBALL_2B_CFB_LARGE_ROAD_FAVORITE_FADE",
        "Large Week 0/1 Road-Favorite Fade",
        "ncaaf",
        "spread",
        "Road favorites laying 14+: 16-32 ATS since 2013",
        ("week", "away_spread"),
        parent="FOOTBALL_2_CFB_ROAD_FAVORITE_FADE",
    ),
)

SYSTEMS = PRIMARY_SYSTEMS + SUBSET_SYSTEMS
