import pytest
from datetime import datetime, timezone
from server.odds.player_names import normalize_player_name
from server.odds.normalize import rows_to_games

PAIRS = [('Bobby Witt','Bobby Witt Jr.'), ('Daniel Lynch','Daniel Lynch IV'),
         ('Michael Harris','Michael Harris II'), ('Ronald Acuña','Ronald Acuna Jr.'),
         ('Fernando Tatis','Fernando Tatis Jr.'), ('Francis Lindor','Francisco Lindor')]

@pytest.mark.parametrize('raw,canonical', PAIRS)
def test_mlb_aliases(raw,canonical):
    assert normalize_player_name(raw,'mlb') == normalize_player_name(canonical,'mlb')
    assert normalize_player_name(raw,'nfl') != normalize_player_name(canonical,'nfl')


def test_luis_garcia_is_scoped_to_batter_markets():
    assert normalize_player_name('Luis Garcia','mlb','batter_total_bases') == 'luis garcia jr'
    assert normalize_player_name('Luis Garcia','mlb','batter_total_bases_alternate') == 'luis garcia jr'
    assert normalize_player_name('Luis Garcia','mlb','pitcher_strikeouts') == 'luis garcia'
    assert normalize_player_name('Luis Garcia','mlb') == 'luis garcia'

@pytest.mark.parametrize('raw,canonical,market', [(a,b,'pitcher_strikeouts' if a=='Daniel Lynch' else 'batter_total_bases') for a,b in PAIRS]+[('Luis Garcia','Luis Garcia Jr.','batter_total_bases')])
def test_cached_coral_pairs_with_alternate_props(raw,canonical,market):
    common=dict(event_id='g',sport_key='mlb',home_team='Home',away_team='Away',commence_time='2026-09-10T00:00:00Z',outcome_point=1.5,fetched_at='2026-09-09T20:00:00Z',price_american=-110)
    rows=[dict(common,bookmaker_key='coral33',market_key=market,outcome_name=raw+' Over'),
          dict(common,bookmaker_key='draftkings',market_key=market+'_alternate',outcome_name=canonical+' Over')]
    games=rows_to_games(rows,datetime(2026,9,9,20,1,tzinfo=timezone.utc))
    outcomes=games[0]['markets'][0]['outcomes']
    assert len(outcomes)==1
    assert len(outcomes[0]['prices'])==2
