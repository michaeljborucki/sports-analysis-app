"""Feed spellings ESPN abbreviates, which no structural rule can bridge."""
from server.systems.team_names import TeamIndex, normalize


def _index() -> TeamIndex:
    idx = TeamIndex()
    idx.add("2545", "se-la", "SE Louisiana Lions", "SE Louisiana", mascot="Lions")
    idx.add("2572", "usm", "Southern Miss Golden Eagles", "Southern Miss",
            mascot="Golden Eagles")
    idx.add("2546", "southeastern-mo", "Southeast Missouri State Redhawks",
            mascot="Redhawks")
    return idx


def test_feed_spellings_resolve_to_espn_abbreviations():
    idx = _index()
    assert idx.resolve("Southeastern Louisiana Lions") == "se-la"
    assert idx.resolve("Southern Mississippi Golden Eagles") == "usm"


def test_aliases_normalize_to_the_provider_spelling():
    assert normalize("Southeastern Louisiana") == "selouisiana"
    assert normalize("Southern Mississippi") == "southernmiss"


def test_a_different_southeast_school_is_not_swallowed():
    idx = _index()
    assert idx.resolve("Southeast Missouri State Redhawks") == "southeastern-mo"
