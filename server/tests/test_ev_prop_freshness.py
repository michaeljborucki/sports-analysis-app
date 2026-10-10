from datetime import datetime,timedelta,timezone
import pytest
from server.odds.ev import scan_all_ev
NOW=datetime(2026,9,9,18,tzinfo=timezone.utc)

def scan(age=600,offer_age=30,hours=4,market='batter_total_bases',book='pinnacle',sport='mlb'):
    def price(b,p,a):return dict(bookmaker_key=b,price_american=p,point=1.5,fetched_at=NOW-timedelta(seconds=a))
    game=dict(event_id='g',sport_key=sport,home_team='Home',away_team='Away',commence_time=NOW+timedelta(hours=hours),markets=[dict(market_key=market,outcomes=[
        dict(outcome_name='test player Over',prices=[price(book,-110,age),price('coral33',120,offer_age)]),
        dict(outcome_name='test player Under',prices=[price(book,-110,age),price('coral33',-130,offer_age)])])])
    return scan_all_ev([game],now=NOW,books_filter={'coral33'},min_ev_pct=1,stale_seconds=300)

def test_delayed_prop_reference_visible_with_age_and_flag():
    rows=scan()
    assert rows
    assert rows[0]['anchor_age_s']==600
    assert rows[0]['reference_delayed'] is True
    assert rows[0]['offered_age_s']==30

@pytest.mark.parametrize('kwargs',[dict(offer_age=301),dict(age=1021),dict(hours=.5,age=421),dict(market='team_totals')])
def test_offer_and_reference_expiry(kwargs):
    assert scan(**kwargs)==[]

def test_recent_reference_is_not_flagged():
    rows=scan(age=60)
    assert rows[0]['reference_delayed'] is False

def test_consensus_records_reference_age():
    # A second sharp book supplies the complete pair needed for consensus.
    from server.odds.ev import _consensus_fair
    def p(age):return dict(price_american=-110,fetched_at=NOW-timedelta(seconds=age))
    # (lowvig duplicates betonlineag — one operator — so use a distinct book.)
    pairs={('a Over',1.5):{'betonlineag':p(600),'fanduel':p(700)},
           ('a Under',1.5):{'betonlineag':p(620),'fanduel':p(720)}}
    ages={}
    assert _consensus_fair(pairs,'batter_total_bases',NOW,1020,frozenset({'betonlineag','fanduel'}),ages)
    assert set(ages.values())=={720}


def test_one_operator_is_not_a_consensus():
    """2026-10-10: betonlineag and lowvig post the same lines; together they
    are ONE opinion, so they can't form a 2-book consensus."""
    from server.odds.ev import _consensus_fair
    def p(age):return dict(price_american=-110,fetched_at=NOW-timedelta(seconds=age))
    pairs={('a Over',1.5):{'betonlineag':p(60),'lowvig':p(60)},
           ('a Under',1.5):{'betonlineag':p(60),'lowvig':p(60)}}
    assert _consensus_fair(pairs,'batter_total_bases',NOW,1020,frozenset({'betonlineag','lowvig'}),{}) is None


def test_novig_taker_prices_never_form_the_fair():
    """Novig's taker price is 1 - the best bid on the other side, which can be
    the maker's own quote: it must not pull the fair toward that side."""
    from server.odds.ev import _consensus_fair
    def p(price):return dict(price_american=price,fetched_at=NOW-timedelta(seconds=60))
    pairs={('a Over',1.5):{'fanduel':p(-110),'novig':p(-200)},
           ('a Under',1.5):{'fanduel':p(-110),'novig':p(150)}}
    assert _consensus_fair(pairs,'batter_total_bases',NOW,1020,frozenset(),{}) is None   # only 1 real book
    pairs[('a Over',1.5)]['draftkings']=p(-110); pairs[('a Under',1.5)]['draftkings']=p(-110)
    used=set()
    fair,n=_consensus_fair(pairs,'batter_total_bases',NOW,1020,frozenset(),{},used)
    assert n==2 and used=={'fanduel','draftkings'} and abs(fair[('a Over',1.5)]-0.5)<1e-9


def test_explicit_stricter_limit_preserved():
    from server.odds.ev import prop_reference_limit
    assert prop_reference_limit({'commence_time':NOW+timedelta(hours=4)},'batter_total_bases',NOW,60)==60


def test_distant_props_reference_expires_after_one_cycle():
    assert scan(hours=24,age=3600)
    assert scan(hours=24,age=3721)==[]


def test_nfl_faster_polling_tightens_reference_expiry():
    assert scan(sport='nfl',market='player_receptions',age=290)
    assert scan(sport='nfl',market='player_receptions',age=301)==[]
    assert scan(sport='nfl',market='player_receptions',hours=24,age=700)
    assert scan(sport='nfl',market='player_receptions',hours=24,age=721)==[]


def test_main_line_reference_follows_collector_cadence():
    # h2h at 24h out: betting-db polls every 30 min -> 1920s allowed.
    assert scan(market='h2h', hours=24, age=1800)
    assert scan(market='h2h', hours=24, age=1921) == []
    # 1-12h band: 300s polls -> 420s allowed.
    assert scan(market='h2h', hours=4, age=400)
    assert scan(market='h2h', hours=4, age=421) == []
    # Inside 1h the 300s default stands.
    assert scan(market='h2h', hours=.5, age=301) == []


def test_novig_offer_follows_its_rest_poll_cadence():
    from server.odds.ev import offer_limit
    g = {'commence_time': NOW + timedelta(hours=24)}
    assert offer_limit('novig_maker', g, NOW, 300) == 900 + 120
    assert offer_limit('coral33', g, NOW, 300) == 300
    assert offer_limit('novig_maker', g, NOW, 60) == 60      # strict callers stay strict
