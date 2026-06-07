from unittest.mock import patch, MagicMock
from scrapers.schedule import get_upcoming_events, FightCard, Fight


def test_fight_card_structure():
    card = FightCard(
        event_name="UFC 300",
        date="2026-04-12",
        fights=[
            Fight(
                fighter_a="Islam Makhachev",
                fighter_b="Charles Oliveira",
                weight_class="Lightweight",
                card_position="main_event",
                rounds=5,
                is_title_fight=True,
            )
        ],
    )
    assert card.event_name == "UFC 300"
    assert len(card.fights) == 1
    assert card.fights[0].rounds == 5
    assert card.fights[0].is_title_fight is True


def test_fight_defaults():
    f = Fight(fighter_a="A", fighter_b="B", weight_class="Lightweight")
    assert f.card_position == "main_card"
    assert f.rounds == 3
    assert f.is_title_fight is False


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_events_parses_html(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html><body>
    <table class="b-statistics__table-events">
      <tr class="b-statistics__table-row">
        <td class="b-statistics__table-col">
          <a href="http://ufcstats.com/event-details/abc123" class="b-link">UFC 300</a>
        </td>
        <td class="b-statistics__table-col">April 12, 2026</td>
      </tr>
    </table>
    </body></html>
    """
    mock_get.return_value = mock_resp

    events = get_upcoming_events()
    assert isinstance(events, list)
    assert len(events) == 1
    assert events[0]["event_name"] == "UFC 300"
