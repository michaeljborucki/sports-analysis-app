"""Cricket news and squad availability."""
from dataclasses import dataclass, field
import requests
from config import CRICKET_API_KEY, CRICKET_API_BASE


@dataclass
class SquadUpdate:
    team: str
    league: str
    available: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    notes: str = ""


def get_squad_updates(league: str) -> list[SquadUpdate]:
    """Fetch squad/availability updates. Stub for now."""
    return []
