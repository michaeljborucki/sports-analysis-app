from server.odds.mapping_health import MappingHealth
from server.odds.player_names import normalize_player_name


def test_confirmed_nfl_alias():
    assert normalize_player_name('Andy Borregales', 'nfl') == normalize_player_name('Andres Borregales', 'nfl')


def test_persistent_counts_and_resolution(tmp_path):
    path = tmp_path / 'mapping.sqlite'
    tracker = MappingHealth(path)
    def row(book, name, point=1):
        return dict(sport_key='nfl', event_id='game', market_key='player_pass_yds',
                    bookmaker_key=book, outcome_name=name+' Over', outcome_point=point)
    rows = [row('coral33', 'J Smith'), row('other', 'John Smith', 2)]
    tracker.audit_players(rows)
    tracker.audit_players(rows)
    issue = MappingHealth(path).listing()['issues'][0]
    assert issue['hits'] == 2
    assert issue['kind'] == 'player_name'
    assert issue['candidates'] == ['john smith']
    tracker.audit_players([])
    assert tracker.listing()['issues'][0]['resolved'] == 0
    tracker.audit_players([row('coral33', 'J Smith'), row('other', 'Smith', 2)])
    assert tracker.listing()['issues'][0]['resolved'] == 1


def test_candidates_do_not_cross_event_or_stat(tmp_path):
    tracker = MappingHealth(tmp_path / 'mapping.sqlite')
    rows = [dict(sport_key='nfl',event_id='a',market_key='player_pass_yds',bookmaker_key='coral33',outcome_name='J Smith Over'),
            dict(sport_key='nfl',event_id='b',market_key='player_pass_yds',bookmaker_key='other',outcome_name='John Smith Over')]
    tracker.audit_players(rows)
    assert tracker.listing()['issues'][0]['kind'] == 'player_coverage'


def test_coral_reports_raw_team_and_unknown_stat(tmp_path):
    from datetime import datetime, timezone
    from server.odds.books.coral33.normalizer import normalize_league_lines, normalize_player_props
    tracker = MappingHealth(tmp_path / 'mapping.sqlite')
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    line = dict(Status='O', Team1ID='NE Patriots', Team2ID='SEA Seahawks',
                GameDateTime='2026-09-09 18:20:01.000')
    normalize_league_lines({'Lines': [line]}, 'Game', 'nfl', now,
                           lambda *args: None, report_issue=tracker.record)
    prop = dict(Status='O', Team1ID='Test Player', Team2ID='Mystery Stat', CorrelationID='123-g')
    normalize_player_props({'Lines': [prop]}, 'nfl', now, lambda _: None, report_issue=tracker.record)
    issues = {i['kind']: i for i in tracker.listing()['issues']}
    assert issues['team']['raw_name'] == 'NE Patriots / SEA Seahawks'
    assert issues['stat']['raw_name'] == 'Mystery Stat'
    assert issues['stat']['event'] == '123-g'
    normalize_league_lines({'Lines': [line]}, 'Game', 'nfl', now,
                           lambda *args: dict(event_id='game',home_team='Seattle Seahawks',away_team='New England Patriots'),
                           report_issue=tracker.record)
    assert next(i for i in tracker.listing()['issues'] if i['kind'] == 'team')['resolved'] == 1


def test_team_candidates_exclude_other_kickoff_times():
    from server.odds.mapping_health import team_candidates
    events = [dict(away_team='New England Patriots', home_team='Seattle Seahawks', commence_time='2026-09-10T00:20:00Z')]
    assert team_candidates('Patriots / Seahawks', '2026-09-10T00:20:00Z', events)
    assert team_candidates('Patriots / Seahawks', '2026-09-11T00:20:00Z', events) == []


def test_cached_alias_rows_merge_using_freshest_price():
    from server.odds.normalize import rows_to_games
    common = dict(event_id='game',sport_key='nfl',home_team='Home',away_team='Away',
                  commence_time='2026-09-10T00:20:00Z',market_key='player_kicking_points',
                  bookmaker_key='coral33',outcome_point=6.5)
    old = dict(common,outcome_name='andy borregales Over',price_american=-110,fetched_at='2026-09-09T19:00:00Z')
    new = dict(common,outcome_name='andres borregales Over',price_american=-120,fetched_at='2026-09-09T19:01:00Z')
    from datetime import datetime, timezone
    for rows in ([old,new],[new,old]):
        games = rows_to_games(rows, datetime(2026,9,9,19,2,tzinfo=timezone.utc))
        outcomes = games[0]['markets'][0]['outcomes']
        assert len(outcomes) == 1
        assert outcomes[0]['outcome_name'] == 'andres borregales Over'
        assert len(outcomes[0]['prices']) == 1
        assert outcomes[0]['prices'][0]['price_american'] == -120
