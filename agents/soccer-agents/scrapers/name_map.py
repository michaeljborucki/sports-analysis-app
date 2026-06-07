"""Team name normalization between Odds API and ESPN."""
import logging
from unidecode import unidecode

logger = logging.getLogger("mirofish.scrapers.name_map")

# Known mismatches: Odds API name -> ESPN name
# Add entries as you discover them
KNOWN_MAPPINGS = {
    # MLS
    "CF Montreal": "CF Montréal",
    "Columbus Crew SC": "Columbus Crew",
    "Inter Miami": "Inter Miami CF",
    "New York City": "New York City FC",
    "NYCFC": "New York City FC",
    "NY Red Bulls": "New York Red Bulls",
    "New York Red Bulls": "Red Bull New York",
    "DC United": "D.C. United",
    "LA Galaxy": "LA Galaxy",
    "LAFC": "LAFC",
    "Los Angeles FC": "LAFC",
    "St. Louis CITY SC": "St. Louis CITY SC",
    "St Louis City SC": "St. Louis CITY SC",
    "St. Louis City SC": "St. Louis CITY SC",
    "Nashville": "Nashville SC",
    "Nashville SC": "Nashville SC",
    "Chicago Fire": "Chicago Fire FC",
    "Houston Dynamo": "Houston Dynamo FC",
    "Vancouver Whitecaps FC": "Vancouver Whitecaps",
    # EPL
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
    "Spurs": "Tottenham Hotspur",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Man Utd": "Manchester United",
    "Nott'm Forest": "Nottingham Forest",
    "Nottingham Forest": "Nottingham Forest",
    "West Ham": "West Ham United",
    "Ipswich": "Ipswich Town",
    "Leicester": "Leicester City",
    "Newcastle": "Newcastle United",
    "Bournemouth": "AFC Bournemouth",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Brighton": "Brighton & Hove Albion",
    "Leeds United": "Leeds United",
    "Sunderland": "Sunderland",
    # Serie A
    "AC Milan": "AC Milan",
    "Inter": "Internazionale",
    "Inter Milan": "Internazionale",
    "Atalanta BC": "Atalanta",
    "Hellas Verona": "Hellas Verona",
    "Hellas Verona FC": "Hellas Verona",
    "AS Roma": "AS Roma",
    "Lazio": "Lazio",
    "SS Lazio": "Lazio",
    # Eredivisie
    "PSV": "PSV Eindhoven",
    "AZ": "AZ Alkmaar",
    "Ajax": "Ajax Amsterdam",
    "Feyenoord": "Feyenoord Rotterdam",
    "FC Twente Enschede": "FC Twente",
    "FC Zwolle": "PEC Zwolle",
    "Groningen": "FC Groningen",
    "SC Telstar": "Telstar",
}


def normalize_team_name(name: str, league: str = None) -> str:
    """Normalize a team name to match ESPN's naming convention.

    1. Check exact match in KNOWN_MAPPINGS
    2. Check case-insensitive match
    3. Check unidecoded match (handles accents)
    4. Return original if no match found
    """
    if not name:
        return name

    # Exact match
    if name in KNOWN_MAPPINGS:
        return KNOWN_MAPPINGS[name]

    # Case-insensitive match
    name_lower = name.lower()
    for key, value in KNOWN_MAPPINGS.items():
        if key.lower() == name_lower:
            return value

    # Unidecode match (strip accents)
    name_ascii = unidecode(name)
    for key, value in KNOWN_MAPPINGS.items():
        if unidecode(key) == name_ascii:
            return value

    return name


def build_league_name_map(odds_names: list[str], espn_names: list[str]) -> dict:
    """Auto-build name mapping by fuzzy matching Odds API names to ESPN names.

    Uses substring matching and unidecode for accent normalization.
    Call this once per pipeline run to discover new mappings.
    """
    mapping = {}
    for odds_name in odds_names:
        # Try exact match first
        if odds_name in espn_names:
            mapping[odds_name] = odds_name
            continue

        # Try unidecoded match
        odds_ascii = unidecode(odds_name).lower()
        for espn_name in espn_names:
            espn_ascii = unidecode(espn_name).lower()
            if odds_ascii == espn_ascii:
                mapping[odds_name] = espn_name
                break
        else:
            # Try substring match (e.g., "Columbus Crew" matches "Columbus Crew SC")
            for espn_name in espn_names:
                espn_ascii = unidecode(espn_name).lower()
                if odds_ascii in espn_ascii or espn_ascii in odds_ascii:
                    mapping[odds_name] = espn_name
                    break
            else:
                # No match found
                logger.warning("[name_map] No ESPN match for Odds API team: %s", odds_name)
                mapping[odds_name] = odds_name

    return mapping
