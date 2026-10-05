"""Which side of a total a leg took.

Coral33 puts the side only in the description text — `chosen_team` is just
"Team1/Team2" on a total — and on a parlay every leg's description is
concatenated into one string, so the side must be located by the leg's own
total rather than by position.
"""
from server.odds.books.coral33.accounts import _total_side


def test_reads_the_side_off_a_single_leg():
    assert _total_side("Football #211 Oregon St/Houston O 50&#189; -110 - For Game", 50.5) == "over"
    assert _total_side("Football #186 Ohio/Nebraska U 47 -110 - For Game", 47.0) == "under"


def test_half_point_entity_and_literal_both_parse():
    assert _total_side("Baseball #905 Giants/Mets O 10&#189; +270", 10.5) == "over"
    assert _total_side("Baseball #905 Giants/Mets O 10½ +270", 10.5) == "over"


def test_a_parlays_shared_description_resolves_each_leg_by_its_own_total():
    # One string, two legs, opposite sides — the real shape from the feed.
    shared = (
        "Baseball #978 Marlins/Royals U 5&#189; -120 - For 1st 5 Innings "
        "Soccer #200377 Derby County/West Ham O 3 +115 - For Game"
    )
    assert _total_side(shared, 5.5) == "under"
    assert _total_side(shared, 3.0) == "over"


def test_ambiguity_and_absence_refuse_rather_than_guess():
    # Same total on both sides inside one description — unknowable.
    assert _total_side("A/B O 45 -110 C/D U 45 -110", 45.0) is None
    # A spread leg carries no side.
    assert _total_side("Football #149 Toledo 10&#189; -120 - buying &#189;", None) is None
    assert _total_side(None, 50.5) is None
    # A number that is not this leg's total must not be borrowed.
    assert _total_side("Football #211 Oregon St/Houston O 50&#189; -110", 47.0) is None


def test_team_letters_are_not_mistaken_for_a_side():
    # "Ohio" starts with O; only a standalone O/U before the number counts.
    assert _total_side("Football #186 Ohio/Nebraska U 47 -110", 47.0) == "under"
    assert _total_side("Football #155 Miami Ohio +16&#189; -110", None) is None


def test_split_quarter_lines_are_averaged():
    """Coral33 writes a split line as a pair; AdjTotalPoints is the midpoint."""
    a = "Football #193 UAB/Illinois O 54 -110 - For Game Soccer #207013 Celtic/St. Mirren O 3,3&#189; -125 - For Game"
    assert _total_side(a, 3.25) == "over"   # the 3 / 3.5 split
    assert _total_side(a, 54.0) == "over"   # the plain leg in the same string

    b = "Football #143 Akron +27 -110 - For Game Soccer #203877 PSV Eindhoven/Ajax O 3&#189;,4 -105 - For Game"
    assert _total_side(b, 3.75) == "over"   # the 3.5 / 4 split

    c = "Soccer #1 A/B U 2,2&#189; -110"
    assert _total_side(c, 2.25) == "under"
    # The halves of a split must not be read as standalone totals.
    assert _total_side(c, 2.0) is None
    assert _total_side(c, 2.5) is None
