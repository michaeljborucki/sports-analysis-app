from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from server.odds.books.coral33.event_matcher import Coral33EventMatcher
from server.odds.books.coral33.mapping import load_coral33_config

PAIRS = {
'ncaaf': [('Southern Miss','Southern Mississippi Golden Eagles'),('Middle Tennessee St','Middle Tennessee Blue Raiders'),('Connecticut','UConn Huskies'),('Central Florida','UCF Knights'),('UL Lafayette','Louisiana Ragin Cajuns')],
'asian_baseball': [('Rakuten Golden Eagles','Tohoku Rakuten Golden Eagles'),('Nippon Ham Fighters','Hokkaido Nippon-Ham Fighters'),('Fukuoka S Hawks','Fukuoka SoftBank Hawks')],
'soccer': [('Machida Zelvia','FC Machida Zelvia'),('Tokyo','FC Tokyo'),('Mito','Mito HollyHock'),('Kyoto Sanga','Kyoto Purple Sanga'),('RB Bragantino','Bragantino-SP'),('SC Internacional','Internacional'),('Atletico PR','Atletico Paranaense'),('Juarez','FC Juárez'),('UANL Tigres','Tigres'),('Atlante','Atlante FC'),('Club Tijuana','Tijuana'),('Club Leon','León'),('UNAM Pumas','Pumas'),('Los Angeles Galaxy','LA Galaxy'),('Vancouver Whitecaps','Vancouver Whitecaps FC'),('San Diego','San Diego FC'),('Minnesota United','Minnesota United FC'),('Inter Miami','Inter Miami CF'),('Atlanta United','Atlanta United FC'),('Columbus Crew','Columbus Crew SC'),('Sabah Baku','Sabah FK'),('Bodo Glimt','Bodø/Glimt'),('Lens','RC Lens'),('Le Mans','Le Mans FC'),('Toulouse FC','Toulouse'),('Angers SCO','Angers'),('Stade Rennais','Rennes'),('FC Koln','1. FC Köln'),('Freiburg','SC Freiburg'),('Paderborn','SC Paderborn'),('Stuttgart','VfB Stuttgart'),('Hoffenheim','TSG Hoffenheim'),('Schalke 04','FC Schalke 04'),('Torino FC','Torino'),('Atalanta','Atalanta BC'),('Barcelona FC','Barcelona'),('Celta de Vigo','Celta Vigo'),('Elche','Elche CF'),('Osasuna','CA Osasuna'),('Racing Santander','Real Racing Club de Santander'),('Brighton & Hove','Brighton and Hove Albion'),('Coventry','Coventry City')],
}

@pytest.mark.parametrize('sport,raw,canonical',[(s,a,b) for s,ps in PAIRS.items() for a,b in ps])
def test_observed_team_variants_match_only_same_fixture(sport,raw,canonical):
    cfg=load_coral33_config(Path('server/config/coral33.toml'))
    now=datetime(2026,9,12,19,tzinfo=timezone.utc)
    events=[dict(event_id='target',home_team=canonical,away_team='Distinct Opponent',commence_time=now)]
    matcher=Coral33EventMatcher(lambda key: events if key==sport else [],cfg.team_aliases)
    match=matcher.match(sport,raw,'Distinct Opponent',now+timedelta(seconds=1))
    assert match and match['event_id']=='target'
    assert matcher.match(sport,raw,'Wrong Opponent',now) is None
    assert matcher.match(sport,raw,'Distinct Opponent',now+timedelta(days=1)) is None
