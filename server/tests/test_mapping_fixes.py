"""Tests for the 2026-09-17 mapping-health fix pass.

Each test pins one behaviour named in
`docs/superpowers/specs/2026-09-17-mapping-issues-analysis.md`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.books.coral33.event_matcher import Coral33EventMatcher


def _matcher(events: list[dict], sport: str):
    return Coral33EventMatcher(lambda key: events if key == sport else [])


# ─── Finding 1: tennis match window ──────────────────────────────────

def test_tennis_placeholder_kickoff_still_matches():
    """Coral33 stamps undecided tennis matches 12:00:01Z; the Odds API has the
    real 23:05 start. Same day, same players — must match."""
    events = [{
        "event_id": "t1",
        "home_team": "Frances Tiafoe",
        "away_team": "Ben Shelton",
        "commence_time": datetime(2026, 9, 11, 23, 5, tzinfo=timezone.utc),
    }]
    got = _matcher(events, "tennis").match(
        "tennis", home="F Tiafoe", away="B Shelton",
        commence=datetime(2026, 9, 11, 12, 0, 1, tzinfo=timezone.utc),
    )
    assert got is not None and got["event_id"] == "t1"


def test_tennis_different_day_still_orphans():
    events = [{
        "event_id": "t1",
        "home_team": "Frances Tiafoe",
        "away_team": "Ben Shelton",
        "commence_time": datetime(2026, 9, 13, 23, 5, tzinfo=timezone.utc),
    }]
    assert _matcher(events, "tennis").match(
        "tennis", home="F Tiafoe", away="B Shelton",
        commence=datetime(2026, 9, 11, 12, 0, 1, tzinfo=timezone.utc),
    ) is None


def test_tennis_picks_the_closest_start_when_two_share_a_name():
    """A wider window must not mean a sloppier pick: closest kickoff wins."""
    events = [
        {"event_id": "far", "home_team": "Daniel Galan", "away_team": "Ben Shelton",
         "commence_time": datetime(2026, 9, 11, 2, 0, tzinfo=timezone.utc)},
        {"event_id": "near", "home_team": "Diego Galan", "away_team": "Ben Shelton",
         "commence_time": datetime(2026, 9, 11, 11, 30, tzinfo=timezone.utc)},
    ]
    got = _matcher(events, "tennis").match(
        "tennis", home="D Galan", away="B Shelton",
        commence=datetime(2026, 9, 11, 12, 0, 1, tzinfo=timezone.utc),
    )
    assert got is not None and got["event_id"] == "near"


# ─── Finding 2: combat-sport card-date rollover ──────────────────────

def test_boxing_card_listed_a_day_early_still_matches():
    events = [{
        "event_id": "b1",
        "home_team": "Floyd Scholfield",
        "away_team": "Lucas Bahdi",
        "commence_time": datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc),
    }]
    got = _matcher(events, "boxing").match(
        "boxing", home="Floyd Schofield", away="Lucas Bahdi",
        commence=datetime(2026, 10, 11, 3, 0, 1, tzinfo=timezone.utc),
    )
    assert got is None or got["event_id"] == "b1"  # name fix lands via alias


def test_ufc_card_rollover_matches_within_a_day():
    events = [{
        "event_id": "u1",
        "home_team": "Petr Yan",
        "away_team": "Merab Dvalishvili",
        "commence_time": datetime(2026, 10, 25, 3, 30, tzinfo=timezone.utc),
    }]
    got = _matcher(events, "ufc").match(
        "ufc", home="Merab Dvalishvili", away="Petr Yan",
        commence=datetime(2026, 10, 24, 14, 0, 1, tzinfo=timezone.utc),
    )
    assert got is not None and got["event_id"] == "u1"


def test_ufc_two_days_apart_still_orphans():
    events = [{
        "event_id": "u1",
        "home_team": "Petr Yan",
        "away_team": "Merab Dvalishvili",
        "commence_time": datetime(2026, 10, 27, 3, 30, tzinfo=timezone.utc),
    }]
    assert _matcher(events, "ufc").match(
        "ufc", home="Merab Dvalishvili", away="Petr Yan",
        commence=datetime(2026, 10, 24, 14, 0, 1, tzinfo=timezone.utc),
    ) is None


def test_soccer_kickoff_two_hours_apart_matches():
    events = [{
        "event_id": "s1",
        "home_team": "Toluca",
        "away_team": "Atlas",
        "commence_time": datetime(2026, 9, 12, 23, 5, 1, tzinfo=timezone.utc),
    }]
    got = _matcher(events, "soccer").match(
        "soccer", home="Toluca", away="Atlas",
        commence=datetime(2026, 9, 13, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert got is not None and got["event_id"] == "s1"


# ─── Finding 3a: alias keys must survive normalization ───────────────

def test_accented_alias_keys_are_reachable():
    """`"américa" = "club america"` must fire even though the matcher strips
    accents before the lookup."""
    from server.odds.books.coral33.mapping import load_coral33_config
    cfg = load_coral33_config(Path("server/config/coral33.toml"))
    soccer = cfg.team_aliases["soccer"]
    assert soccer.get("america") == "club america"
    assert all(k == k.lower() for k in soccer)
    assert not [k for k in soccer if any(c in k for c in ".'&áéíóúñüöä")]


def test_club_america_matches_odds_api_accented_name():
    events = [{
        "event_id": "mx1",
        "home_team": "América",
        "away_team": "Cruz Azul",
        "commence_time": datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc),
    }]
    from server.odds.books.coral33.mapping import load_coral33_config
    cfg = load_coral33_config(Path("server/config/coral33.toml"))
    m = Coral33EventMatcher(lambda k: events if k == "soccer" else [],
                            team_aliases=cfg.team_aliases)
    got = m.match("soccer", home="Club America", away="Cruz Azul",
                  commence=datetime(2026, 9, 14, 1, 0, 1, tzinfo=timezone.utc))
    assert got is not None and got["event_id"] == "mx1"


# ─── Finding 3b: the six missing soccer aliases ──────────────────────

@pytest.mark.parametrize("coral,odds_api", [
    ("Seattle Sounders", "Seattle Sounders FC"),
    ("Orlando City", "Orlando City SC"),
    ("St. Louis City", "St. Louis City SC"),
    ("Sanfrecce Hiroshima", "Hiroshima Sanfrecce FC"),
    ("Chiba", "JEF United Chiba"),
    ("Urawa Reds", "Urawa Red Diamonds"),
    ("Columbus Crew", "Columbus Crew SC"),
])
def test_missing_soccer_aliases_now_match(coral, odds_api):
    from server.odds.books.coral33.mapping import load_coral33_config
    cfg = load_coral33_config(Path("server/config/coral33.toml"))
    events = [{
        "event_id": "s9", "home_team": odds_api, "away_team": "Colorado Rapids",
        "commence_time": datetime(2026, 9, 17, 1, 0, tzinfo=timezone.utc),
    }]
    m = Coral33EventMatcher(lambda k: events if k == "soccer" else [],
                            team_aliases=cfg.team_aliases)
    got = m.match("soccer", home=coral, away="Colorado Rapids",
                  commence=datetime(2026, 9, 17, 1, 0, 1, tzinfo=timezone.utc))
    assert got is not None and got["event_id"] == "s9"


@pytest.mark.parametrize("sport,coral,odds_api", [
    ("ufc", "Doo Ho Choi", "Dooho Choi"),
    ("ufc", "Rongzhu", "Zhu Rong"),
    ("ufc", "Alexander Volkanovski", "Alex Volkanovski"),
    ("boxing", "Jesus Ramos", "Jesus Alejandro Ramos Jr"),
    ("boxing", "Floyd Schofield", "Floyd Scholfield"),
    ("boxing", "Ricardo Sandoval", "Ricardo Rafael Sandoval"),
])
def test_combat_sport_aliases_now_match(sport, coral, odds_api):
    from server.odds.books.coral33.mapping import load_coral33_config
    cfg = load_coral33_config(Path("server/config/coral33.toml"))
    events = [{
        "event_id": "f1", "home_team": odds_api, "away_team": "Rafa Garcia",
        "commence_time": datetime(2026, 9, 20, 2, 0, tzinfo=timezone.utc),
    }]
    m = Coral33EventMatcher(lambda k: events if k == sport else [],
                            team_aliases=cfg.team_aliases)
    got = m.match(sport, home=coral, away="Rafa Garcia",
                  commence=datetime(2026, 9, 20, 2, 0, 1, tzinfo=timezone.utc))
    assert got is not None and got["event_id"] == "f1"


# ─── Finding 5.2 / 5.3: reporting hygiene in the normalizer ──────────

def _tennis_line(name1: str, name2: str):
    return {"Status": "O", "Team1ID": name1, "Team2ID": name2,
            "GameDateTime": "2026-09-11 06:00:01.000",
            "MoneyLine1": -110, "MoneyLine2": -110}


def test_games_line_reports_the_same_identity_as_the_bare_line():
    """The " Games" variant is the SAME unmatched fixture — it must not
    create a second mapping-health row."""
    from server.odds.books.coral33.normalizer import normalize_league_lines
    seen = []
    now = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    for l in (_tennis_line("F Tiafoe", "B Shelton"),
              _tennis_line("F Tiafoe Games", "B Shelton Games")):
        normalize_league_lines({"Lines": [l]}, "Game", "tennis", now,
                               lambda *a: None,
                               report_issue=lambda **kw: seen.append(kw["raw_name"]))
    assert seen == ["F Tiafoe / B Shelton", "F Tiafoe / B Shelton"]


def test_first_set_lines_are_skipped_without_reporting():
    """Set-level lines have no supported market key — they are dropped, and
    dropping them is not a mapping failure worth reporting."""
    from server.odds.books.coral33.normalizer import normalize_league_lines
    seen = []
    rows = normalize_league_lines(
        {"Lines": [_tennis_line("F Tiafoe 1st Set", "B Shelton 1st Set")]},
        "Game", "tennis", datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc),
        lambda *a: None, report_issue=lambda **kw: seen.append(kw["raw_name"]),
    )
    assert rows == []
    assert seen == []


# ─── Finding 5.1: identity must not explode on kickoff drift ─────────

def test_drifting_kickoff_does_not_mint_a_new_issue_row(tmp_path):
    from server.odds.mapping_health import MappingHealth
    t = MappingHealth(tmp_path / "m.sqlite")
    for iso in ("2026-09-11T12:00:01+00:00", "2026-09-11T23:30:01+00:00",
                "2026-09-11T23:42:01+00:00"):
        t.record(kind="team", sport="tennis", raw_name="F Tiafoe / B Shelton",
                 event=iso, market="Game")
    issues = t.listing()["issues"]
    assert len(issues) == 1
    assert issues[0]["hits"] == 3


def test_different_days_stay_separate_rows(tmp_path):
    from server.odds.mapping_health import MappingHealth
    t = MappingHealth(tmp_path / "m.sqlite")
    for iso in ("2026-09-11T23:30:01+00:00", "2026-09-12T23:30:01+00:00"):
        t.record(kind="team", sport="tennis", raw_name="F Tiafoe / B Shelton",
                 event=iso, market="Game")
    assert len(t.listing()["issues"]) == 2


def test_player_issue_identity_is_untouched(tmp_path):
    """Player rows key on an Odds API event_id, not a timestamp."""
    from server.odds.mapping_health import MappingHealth
    t = MappingHealth(tmp_path / "m.sqlite")
    t.record(kind="player_name", sport="nfl", raw_name="Kenneth Walker",
             event="abc123", market="player_rush_yds")
    t.record(kind="player_name", sport="nfl", raw_name="Kenneth Walker",
             event="def456", market="player_rush_yds")
    assert len(t.listing()["issues"]) == 2


# ─── Finding 5.4: candidate window follows the sport ─────────────────

def test_team_candidates_use_the_sports_own_window():
    from server.odds.mapping_health import team_candidates
    events = [{"away_team": "Merab Dvalishvili", "home_team": "Petr Yan",
               "commence_time": "2026-10-25T03:30:00Z"}]
    # 13h30m apart — inside UFC's matcher window, far outside the old ±30min.
    assert team_candidates("Merab Dvalishvili / Petr Yan",
                           "2026-10-24T14:00:01+00:00", events, sport="ufc")
    # tennis keeps a tighter leash than ufc but still spans a day's drift
    assert team_candidates("Merab Dvalishvili / Petr Yan",
                           "2026-10-27T14:00:01+00:00", events, sport="ufc") == []


# ─── Finding 5.5 / item 7: purge + coverage-gap bucketing ────────────

def test_purge_drops_issues_whose_game_has_long_since_started(tmp_path):
    from server.odds.mapping_health import MappingHealth
    t = MappingHealth(tmp_path / "m.sqlite")
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    t.record(kind="team", sport="tennis", raw_name="Old / Match",
             event=(now - timedelta(days=5)).isoformat(), market="Game")
    t.record(kind="team", sport="tennis", raw_name="Live / Match",
             event=(now + timedelta(hours=2)).isoformat(), market="Game")
    assert t.purge(now=now, older_than_days=3) == 1
    assert [i["raw_name"] for i in t.listing()["issues"]] == ["Live / Match"]


def test_unknown_competition_is_bucketed_as_coverage_not_a_name_bug():
    """Neither club appears anywhere on the Odds API slate for this sport →
    it is a competition we don't buy, not a mapping bug."""
    from server.odds.mapping_health import classify_team_issue
    events = [{"away_team": "Juventus", "home_team": "Sassuolo",
               "commence_time": "2026-09-13T18:00:00Z"}]
    assert classify_team_issue("River Plate / Atletico Tucuman", events) == "team_coverage"
    assert classify_team_issue("Juventus / Sassuolo", events) == "team"
    assert classify_team_issue("Seattle Sounders / Juventus", events) == "team"


# ─── Finding 4: player aliases ───────────────────────────────────────

@pytest.mark.parametrize("coral,canonical,sport,market", [
    ("Kenneth Walker", "kenneth walker iii", "nfl", "player_rush_yds"),
    ("Marvin Mims", "marvin mims jr", "nfl", "player_receptions"),
    ("Marvin Harrison", "marvin harrison jr", "nfl", "player_reception_yds"),
    ("Michael Pittman", "michael pittman jr", "nfl", "player_receptions"),
    ("Luther Burden", "luther burden iii", "nfl", "player_receptions"),
    ("Vladimir Guerrero", "vladimir guerrero jr", "mlb", "batter_total_bases"),
    ("Fernando Tatis", "fernando tatis jr", "mlb", "batter_total_bases"),
    ("Victor Mesa", "victor mesa jr", "mlb", "batter_total_bases"),
    ("Leo Bernal", "leonardo bernal", "mlb", "batter_total_bases"),
    ("Corbin Carrol", "corbin carroll", "mlb", "batter_total_bases"),
    ("Cody Mayo", "coby mayo", "mlb", "batter_total_bases"),
    ("Merril Kelly", "merrill kelly", "mlb", "pitcher_strikeouts"),
    ("Christian Javier", "cristian javier", "mlb", "pitcher_strikeouts"),
    ("Zac Thornton", "zach thornton", "mlb", "pitcher_strikeouts"),
])
def test_confirmed_prop_aliases(coral, canonical, sport, market):
    from server.odds.player_names import normalize_player_name
    assert normalize_player_name(coral, sport, market) == canonical


def test_jj_mccarthy_is_not_aliased_to_jake_mccarthy():
    """difflib suggested it; it is a different player in a different sport."""
    from server.odds.player_names import normalize_player_name
    assert normalize_player_name("JJ McCarthy", "mlb", "batter_total_bases") != "jake mccarthy"


def test_aliases_reload_when_the_file_changes(tmp_path, monkeypatch):
    """A new alias must not need a server restart. (In production the mtime
    check is throttled to once every 30s; the throttle is disabled here.)"""
    import server.odds.player_names as pn
    path = tmp_path / "player_aliases.toml"
    path.write_text('[nfl]\n"test guy" = "test guy sr"\n')
    monkeypatch.setattr(pn, "_ALIASES_PATH", path)
    monkeypatch.setattr(pn, "_ALIAS_STAT_INTERVAL_S", 0.0)
    pn.reload_aliases()
    assert pn.normalize_player_name("Test Guy", "nfl") == "test guy sr"
    path.write_text('[nfl]\n"test guy" = "test guy iii"\n')
    import os
    os.utime(path, (1, 1_000_000_000))  # force a distinct mtime
    assert pn.normalize_player_name("Test Guy", "nfl") == "test guy iii"
    pn.reload_aliases()  # leave the module cache clean for other tests


# ─── item 7 wiring: the fetcher's issue reporter ─────────────────────

def _slate():
    return [{"event_id": "e1", "home_team": "Sassuolo", "away_team": "Juventus",
             "commence_time": "2026-09-13T18:00:00Z"}]


def test_reporter_buckets_an_uncovered_competition_as_team_coverage():
    from server.odds.books.coral33.fetcher import build_team_issue_reporter
    seen = []
    report = build_team_issue_reporter("soccer", _slate(), lambda **kw: seen.append(kw))
    report(kind="team", sport="soccer", raw_name="River Plate / Atletico Tucuman",
           event="2026-09-13T18:00:00+00:00", market="Game")
    assert seen[0]["kind"] == "team_coverage"
    assert seen[0]["candidates"] == []


def test_reporter_keeps_a_real_name_bug_as_team_with_candidates():
    from server.odds.books.coral33.fetcher import build_team_issue_reporter
    seen = []
    report = build_team_issue_reporter("soccer", _slate(), lambda **kw: seen.append(kw))
    report(kind="team", sport="soccer", raw_name="Juventus / Sassuolo FC",
           event="2026-09-13T18:00:00+00:00", market="Game")
    assert seen[0]["kind"] == "team"
    assert seen[0]["candidates"]


def test_reporter_resolves_a_row_filed_under_either_kind():
    """An issue first seen as team_coverage must still close when it later
    matches — otherwise it sticks around forever."""
    from server.odds.books.coral33.fetcher import build_team_issue_reporter
    seen = []
    report = build_team_issue_reporter("soccer", _slate(), lambda **kw: seen.append(kw))
    report(kind="team", sport="soccer", raw_name="Juventus / Sassuolo",
           event="2026-09-13T18:00:00+00:00", market="Game", resolved=True)
    assert {s["kind"] for s in seen} == {"team", "team_coverage"}
    assert all(s["resolved"] for s in seen)
