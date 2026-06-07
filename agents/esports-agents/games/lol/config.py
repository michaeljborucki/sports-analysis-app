"""LoL-specific configuration for the MiroFish pipeline."""

BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]

PROB_FIELDS = {
    "moneyline": ["team_a_win_prob", "team_b_win_prob"],
    "map_handicap": ["favorite_cover_prob"],
    "total_maps": ["over_prob", "under_prob", "projected_maps"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "map_handicap": "map_handicap",
    "total_maps": "total_maps",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "team_a_win_prob",
    "map_handicap": "favorite_cover_prob",
    "total_maps": "over_prob",
}

BET_SLOT_FIELDS = {
    "moneyline": ("team_a_win_prob", "team_a", "team_b"),
    "map_handicap": ("favorite_cover_prob", "favorite", "underdog"),
    "total_maps": ("over_prob", "over", "under"),
}

EDGE_THRESHOLDS = {
    "bo1": {"moneyline": 0.07},
    "bo3": {"moneyline": 0.05, "map_handicap": 0.06, "total_maps": 0.05},
    "bo5": {"moneyline": 0.04, "map_handicap": 0.05, "total_maps": 0.04},
}

# LoL has a single map (Summoner's Rift) — this field exists for interface compatibility
ACTIVE_DUTY_MAPS = ["summoners_rift"]

ANALYST_ROLES = ["laning", "macro", "draft", "form", "market", "contrarian"]
