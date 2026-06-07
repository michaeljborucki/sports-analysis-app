"""CS2-specific configuration for the MiroFish pipeline."""

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

# Vote extraction fields: slot -> (section_key, value_field)
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "map_handicap": ("map_handicap", "value_side"),
    "total_maps": ("total_maps", "value_side"),
}

EDGE_THRESHOLDS = {
    "bo1": {
        "moneyline": 0.07,
    },
    "bo3": {
        "moneyline": 0.05,
        "map_handicap": 0.06,
        "total_maps": 0.05,
    },
    "bo5": {
        "moneyline": 0.04,
        "map_handicap": 0.05,
        "total_maps": 0.04,
    },
}

# Last updated: 2026-03-20 — review after each Valve major update
ACTIVE_DUTY_MAPS = [
    "mirage", "inferno", "nuke", "ancient",
    "anubis", "dust2", "vertigo",
]

ANALYST_ROLES = [
    "fragging", "tactical", "map_pool", "form", "market", "contrarian",
]
