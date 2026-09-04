from server.systems.team_names import TeamIndex, normalize


def espn_index() -> TeamIndex:
    index = TeamIndex()
    for team_id, display, location, short in (
        ("399", "UAlbany Great Danes", "UAlbany", "UAlbany"),
        ("2084", "Buffalo Bulls", "Buffalo", "Buffalo"),
        ("194", "Ohio State Buckeyes", "Ohio State", "Ohio State"),
        ("195", "Ohio Bobcats", "Ohio", "Ohio"),
        ("2390", "Miami Hurricanes", "Miami", "Miami"),
        ("193", "Miami (OH) RedHawks", "Miami (OH)", "Miami (OH)"),
        ("2633", "Tennessee Volunteers", "Tennessee", "Tennessee"),
        ("2335", "The Citadel Bulldogs", "The Citadel", "Citadel"),
    ):
        index.add(team_id, team_id, display, location, short)
    return index


def test_u_prefixed_school_matches_the_bare_feed_spelling():
    # The regression: odds feed says "Albany", ESPN says "UAlbany Great Danes".
    assert espn_index().resolve("Albany") == "399"


def test_exact_and_mascot_suffixed_names_still_resolve():
    index = espn_index()
    assert index.resolve("Buffalo Bulls") == "2084"
    assert index.resolve("Buffalo") == "2084"
    assert index.resolve("Tennessee Volunteers") == "2633"


def test_longest_prefix_wins_so_ohio_state_never_collapses_to_ohio():
    index = espn_index()
    assert index.resolve("Ohio State Buckeyes") == "194"
    assert index.resolve("Ohio Bobcats") == "195"


def test_exact_alias_wins_over_an_ambiguous_prefix():
    # ESPN itself calls the Hurricanes "Miami" and the RedHawks "Miami (OH)",
    # so an exact alias hit is decisive even though a prefix scan is not.
    assert espn_index().resolve("Miami") == "2390"


def test_ambiguous_prefix_resolves_to_nothing_rather_than_a_guess():
    # The team-directory feed carries display names only, so "Miami" has no
    # exact alias and prefix-matches two schools. A wrong pick would feed the
    # wrong stadium's weather into a live wager rule, so refuse instead.
    directory = TeamIndex()
    directory.add("2390", "2390", "Miami Hurricanes")
    directory.add("193", "193", "Miami (OH) RedHawks")
    assert directory.resolve("Miami") is None


def test_unknown_team_resolves_to_none():
    assert espn_index().resolve("Nonexistent Tech Aardvarks") is None
    assert espn_index().resolve("") is None


def test_normalize_folds_case_punctuation_and_filler_words():
    assert normalize("Texas A&M Aggies") == "texasamaggies"
    assert normalize("University of Miami") == "miami"
    assert normalize("The Citadel Bulldogs") == "citadelbulldogs"


def directory_index() -> TeamIndex:
    """ESPN's team directory shape: display name plus its trailing mascot."""
    index = TeamIndex()
    for team_id, display in (
        ("248", "Houston Cougars"),
        ("2277", "Houston Christian Huskies"),
        ("2447", "Nicholls Colonels"),
        ("267", "Southeastern Fires"),
        ("2026", "App State Mountaineers"),
        ("2729", "William & Mary Tribe"),
    ):
        school, _, mascot = display.rpartition(" ")
        index.add(team_id, team_id, display, school, mascot=mascot)
    return index


def test_a_longer_school_name_does_not_collapse_onto_a_shorter_one():
    """"Houston Baptist" extends "Houston" but is a different school.

    Refusing here is the point: a wrong match feeds Houston's stadium and
    conference into a Houston Christian game, which is worse than no match.
    """
    index = directory_index()
    assert index.resolve("Houston Cougars") == "248"
    assert index.resolve("Southeastern Louisiana Lions") is None


def test_mascot_corroboration_admits_the_same_school_spelled_longer():
    assert directory_index().resolve("Nicholls State Colonels") == "2447"


def test_known_abbreviations_and_ampersands_resolve():
    index = directory_index()
    assert index.resolve("Appalachian State Mountaineers") == "2026"
    assert index.resolve("Houston Baptist Huskies") == "2277"
    assert index.resolve("William and Mary Tribe") == "2729"
