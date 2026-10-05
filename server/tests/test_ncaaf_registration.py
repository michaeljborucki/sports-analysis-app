from server.sports import SPORTS


def test_college_football_is_registered_with_main_and_first_half_markets():
    sport = SPORTS["ncaaf"]

    assert sport.label == "College Football"
    assert sport.odds_api_sport_keys == (
        "americanfootball_ncaaf",
        "americanfootball_ncaaf_fcs",
    )
    assert [(group.main_key, group.display) for group in sport.market_groups] == [
        ("h2h", "moneyline"),
        ("spreads", "spread"),
        ("totals", "total"),
        ("h2h_h1", "moneyline"),
        ("spreads_h1", "spread"),
        ("totals_h1", "total"),
    ]
