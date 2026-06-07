from briefing import build_briefing


def test_build_briefing_contains_fighter_names():
    fight_data = {
        "event_name": "UFC 300",
        "date": "2026-04-12",
        "fighter_a": {
            "name": "Islam Makhachev",
            "record": "25-1-0",
            "wins_ko": 4, "wins_sub": 11, "wins_dec": 10,
            "stance": "Orthodox", "height": "5'10\"", "reach": "70.5\"",
            "slpm": 2.42, "str_acc": 0.59, "td_avg": 3.15, "td_def": 0.90,
            "sub_avg": 1.2, "avg_fight_time": "12:30", "age": 32,
            "win_streak": 3, "last_5_fights": [],
        },
        "fighter_b": {
            "name": "Charles Oliveira",
            "record": "34-10-0",
            "wins_ko": 10, "wins_sub": 21, "wins_dec": 3,
            "stance": "Orthodox", "height": "5'10\"", "reach": "74\"",
            "slpm": 3.49, "str_acc": 0.56, "td_avg": 2.33, "td_def": 0.53,
            "sub_avg": 1.7, "avg_fight_time": "10:15", "age": 34,
            "win_streak": 0, "last_5_fights": [],
        },
        "weight_class": "Lightweight",
        "rounds": 5,
        "odds": {
            "moneyline": {"fighter_a": -200, "fighter_b": 170},
            "total_rounds": {"line": 2.5, "over_odds": -115, "under_odds": -105},
            "implied_probs": {"fighter_a": 0.65, "fighter_b": 0.35},
        },
        "context_a": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "context_b": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "rankings": {},
    }
    briefing = build_briefing(fight_data)
    assert "Islam Makhachev" in briefing
    assert "Charles Oliveira" in briefing
    assert "UFC 300" in briefing
    assert "Lightweight" in briefing
    assert "FIGHT WINNER" in briefing
    assert "TOTAL ROUNDS" in briefing
    assert "METHOD OF VICTORY" in briefing
    assert "MATCHUP ANALYSIS" in briefing
    assert "Reach Advantage" in briefing
    assert "Stance Matchup" in briefing


def test_build_briefing_handles_missing_data():
    fight_data = {
        "fighter_a": {"name": "Fighter A"},
        "fighter_b": {"name": "Fighter B"},
        "odds": {},
    }
    briefing = build_briefing(fight_data)
    assert "Fighter A" in briefing
    assert "Fighter B" in briefing
