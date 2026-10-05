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
    # Most college rules only speak about FBS-vs-FBS games, so the evaluator
    # drops a confirmed FCS matchup before it ever reaches them. The Game 2
    # reactionary rules are ABOUT facing an FCS opponent, so they opt out and
    # gate on the per-side `home_is_fbs` / `away_is_fbs` fields instead.
    fbs_only: bool = True


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
    fbs_only: bool = True,
) -> SystemDefinition:
    if sport == "ncaaf" and enabled and fbs_only and "is_fbs_game" not in required:
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
        fbs_only=fbs_only,
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
    _s("Football 12", "FOOTBALL_12_NFL_WEEK1_ROAD_DOG_NO_PLAYOFFS", "Week 1 Road Dog, Missed Playoffs", "nfl", "spread", "73-46-4 ATS (61.3%)", ("season_type", "week", "away_spread", "away_made_playoffs_previous_season")),
    _s("Football 13", "FOOTBALL_13_NFL_OVER_AFTER_BOTH_UNDER", "Early Over After Both Teams Went Under", "nfl", "total", "121-81-1 (59.9%)", enabled=False, status="requires_verification"),
    _s("Football 14", "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE", "Week 1 Rest/Experience Advantage", "ncaaf", "spread", "62-39 ATS (61.6%)", ("week", "home_games_played", "away_games_played", "home_spread", "away_spread")),
    _s("Football 15", "FOOTBALL_15_CFB_LOW_TOTAL_FAVORITE_UNDER", "Low-Total Opening-Week Favorite Under", "ncaaf", "total", "51-23 (68.9%) since 2013", ("week", "home_spread", "away_spread", "total")),
    _s("Football 16", "FOOTBALL_16_CFB_G5_HOME_FAVORITE_UNDER", "G5 Non-Conference Home Favorite Under", "ncaaf", "total", "46-27 (63%) since 2013", ("home_conference_class", "away_conference_class", "is_conference_game", "home_spread", "total")),
    _s("Football 17", "FOOTBALL_17_CFB_G5_HOME_UNDERDOG_OVER", "G5 Non-Conference Home Underdog Over", "ncaaf", "total", "23-11 (67.6%) since 2013", ("home_conference_class", "away_conference_class", "is_conference_game", "home_spread", "total")),
    _s("Football 18", "FOOTBALL_18_CFB_NEUTRAL_P4_FAVORITE", "Neutral-Site Power 4 Favorite", "ncaaf", "spread", "Laying 3.5 or less: 10-4-1 ATS; laying 12.5+: 10-3 ATS since 2013", ("week", "neutral_site", "is_conference_game", "home_conference_class", "away_conference_class", "home_spread", "away_spread")),
    _s("Football 19", "FOOTBALL_19_CFB_P4_OPENING_MATCHUP_UNDER", "Opening-Week Power 4 Matchup Under", "ncaaf", "total", "15-6 (71.4%) since 2021", ("week", "is_conference_game", "home_conference_class", "away_conference_class", "total"), status="requires_verification"),
    _s("Football 20", "FOOTBALL_20_CFB_ACC_TIGHT_MATCHUP_UNDER", "ACC Tight-Matchup Under", "ncaaf", "total", "70-48-1 (59.3%) since 2015", ("home_conference_id", "away_conference_id", "home_spread", "total")),
    _s("Football 21", "FOOTBALL_21_CFB_GAME2_FCS_LETDOWN", "Game 2 FCS Letdown Fade", "ncaaf", "spread", "97-120-6 ATS (44.7%) since 2012", ("home_is_fbs", "away_is_fbs", "home_previous_game_played", "away_previous_game_played", "home_spread", "away_spread"), fbs_only=False),
    _s("Football 22", "FOOTBALL_22_CFB_GAME2_FCS_REBOUND_FADE", "Game 2 FCS Rebound Fade", "ncaaf", "spread", "50-71-2 ATS (41.3%) since 2012", ("home_is_fbs", "away_is_fbs", "home_previous_game_played", "away_previous_game_played", "home_spread", "away_spread"), fbs_only=False),
    _s("Football 23", "FOOTBALL_23_CFB_GAME2_HOME_SHUTDOWN_OFFENSE_FADE", "Game 2 Home Fade After Shut-Down Offense", "ncaaf", "spread", "49-63-2 ATS (43.8%) since 2012", ("home_is_fbs", "home_previous_game_played", "home_games_played", "home_spread", "away_spread"), fbs_only=False),
    _s("Football 24", "FOOTBALL_24_CFB_NEUTRAL_REVENGE_UNDERDOG", "Neutral-Site Revenge Underdog", "ncaaf", "spread", "56-37 ATS (60.2%) since 2016", ("neutral_site", "home_revenge", "away_revenge", "home_spread", "away_spread")),
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

# Added 2026-09-10 from the VSiN Week 2 CFB / Week 1 NFL / MLB articles. See
# docs/superpowers/specs/2026-09-10-vsin-*-analysis.md for the sample sizes
# and the reasoning behind which of ~60 published angles made the cut. These
# are PUBLISHED, threshold-mined trends: the source records are a starting
# hypothesis, not a validated edge.
VSIN_2026_SYSTEMS: tuple[SystemDefinition, ...] = (
    _s("Football 25", "FOOTBALL_25_CFB_TWO_RANKED_HOME", "Ranked vs Ranked, Home Side", "ncaaf", "spread", "192-135-9 ATS (58.7%) since 2017", ("home_is_ranked", "away_is_ranked", "neutral_site", "home_spread")),
    _s("Football 26", "FOOTBALL_26_CFB_UNRANKED_ROAD_CLOSE_UNDER", "Unranked Road Team in a Close Spot Under", "ncaaf", "total", "90-59 to the Under (60.4%) since October 2016", ("home_is_ranked", "away_is_ranked", "neutral_site", "away_spread", "total")),
    _s("Football 27", "FOOTBALL_27_CFB_REVENGE_VS_POROUS_DEFENSE", "Revenge vs a Porous Defense", "ncaaf", "spread", "230-182 ATS (55.8%) since 2016", ("home_revenge", "away_revenge", "home_ppg_allowed", "away_ppg_allowed", "home_spread", "away_spread")),
    _s("Football 28", "FOOTBALL_28_CFB_DOMINANT_PERFORMANCE_MOMENTUM", "Momentum Off a Dominant Performance", "ncaaf", "spread", "151-113 ATS (57.2%) over thirteen seasons", ("home_previous_game_played", "away_previous_game_played", "home_spread", "away_spread")),
    _s("Football 29", "FOOTBALL_29_NFL_WEEK1_DIVISIONAL_HOME_DOG", "Week 1 Divisional Home Underdog", "nfl", "spread", "25-9 ATS (73.5%) since 2009", ("season_type", "week", "is_divisional", "home_spread")),
    _s("Football 30", "FOOTBALL_30_NFL_WEEK1_NONCONF_PICKEM_HOME_FADE", "Week 1 Non-Conference Pick'em Home Fade", "nfl", "spread", "3-17-1 ATS since 2015", ("season_type", "week", "is_conference_game", "home_spread", "away_spread")),
    _s("Football 31", "FOOTBALL_31_NFL_WEEK1_ROAD_TEAM_4_TO_6_WINS", "Week 1 Road Team Off a 4-6 Win Season", "nfl", "spread", "56-24-5 ATS (70%) since 2004", ("season_type", "week", "away_prior_season_wins", "away_spread")),
    _s("Football 32", "FOOTBALL_32_NFL_WEEK1_BIG_UNDERDOG", "Week 1 Underdog of 6.5 or More", "nfl", "spread", "32-13-1 ATS (71.1%) since 2013", ("season_type", "week", "home_spread", "away_spread")),
    _s("Football 33", "FOOTBALL_33_NFL_WEEK1_HOME_FAVORITE_VS_WINNING_TEAM", "Week 1 Home Favorite Hosting a Winning Team", "nfl", "spread", "54-30-5 ATS (64.3%) since 2000", ("season_type", "week", "home_spread", "away_prior_season_win_pct")),
    _s("Football 34", "FOOTBALL_34_NFL_WEEK1_DIVISIONAL_ROAD_DOG", "Week 1 Divisional Road Underdog", "nfl", "spread", "22-12-1 ATS (64.7%) since 2013", ("season_type", "week", "is_divisional", "away_spread")),
    _s("Football 35", "FOOTBALL_35_NFL_WEEK1_HIGH_SCORING_FADE", "Week 1 Fade of Last Year's High Scorer", "nfl", "spread", "27-41 ATS (39.7%) since 2013", ("season_type", "week", "home_prior_season_ppg", "away_prior_season_ppg", "home_spread", "away_spread")),
    _s("Football 36", "FOOTBALL_36_NFL_WEEK1_STINGY_DEFENSE", "Week 1 Stingy Defense", "nfl", "spread", "27-13 ATS (67.5%) since 2017", ("season_type", "week", "home_prior_season_ppg_allowed", "away_prior_season_ppg_allowed", "home_spread", "away_spread")),
    _s("Football 37", "FOOTBALL_37_NFL_WEEK1_CLOSE_LOSS_REBOUND", "Week 1 Close-Loss Rebound", "nfl", "spread", "14-5-1 ATS (73.6%) since 2013", ("season_type", "week", "home_prior_season_close_losses", "away_prior_season_close_losses", "home_spread", "away_spread")),
    _s("Football 38", "FOOTBALL_38_NFL_WEEK1_WIN_COLLAPSE_REBOUND", "Week 1 Rebound After a Win Collapse", "nfl", "spread", "26-13 ATS (66.7%) since 2013", ("season_type", "week", "home_prior_season_win_change", "away_prior_season_win_change", "home_spread", "away_spread")),
    _s("Football 39", "FOOTBALL_39_NFL_WEEK1_WIN_COLLAPSE_UNDER", "Week 1 Win-Collapse Under", "nfl", "total", "28-11 to the Under (71.8%)", ("season_type", "week", "home_prior_season_win_change", "away_prior_season_win_change", "total")),
    _s("MLB 13", "MLB_13_LATE_SEASON_CONTENDER_SMALL_FAVORITE", "Late-Season Contender as a Small Favorite", "mlb", "moneyline", "55-26 (+19.53 units, 24.1% ROI) over five seasons", ("month", "home_win_pct", "away_win_pct", "home_moneyline", "away_moneyline")),
    _s("MLB 14", "MLB_14_SERIES_FINALE_LOSING_STREAK", "Series Finale on a Losing Streak", "mlb", "moneyline", "486-508 (+34.75 units, 3.5% ROI) since 2022", ("series_game_number", "series_length", "home_losing_streak", "away_losing_streak", "home_moneyline", "away_moneyline")),
    _s("MLB 15", "MLB_15_SERIES_FINALE_ROAD_DOG_ENDING_TRIP", "Series Finale Road Dog Ending a Road Trip", "mlb", "moneyline", "422-482 (+86.62 units, 9.6% ROI) since 2022", ("series_game_number", "series_length", "away_moneyline", "away_ends_road_trip")),
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

PRIMARY_SYSTEMS = PRIMARY_SYSTEMS + VSIN_2026_SYSTEMS

SYSTEMS = PRIMARY_SYSTEMS + SUBSET_SYSTEMS
