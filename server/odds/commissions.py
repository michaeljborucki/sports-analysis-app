"""
Commission-on-winnings rates for exchange-style books. Applied when the odds
API response is normalized, so every `price_american` served by the API is
already the effective (post-commission) price. Adjust values here; changes
take effect on the next fetcher tick (or backend restart in frozen mode).
"""
from __future__ import annotations


BOOK_COMMISSION: dict[str, float] = {
    # Big UK/EU exchanges
    "betfair_ex_uk": 0.05,
    "betfair_ex_eu": 0.05,
    "smarkets": 0.02,
    "matchbook": 0.02,
    # US exchanges
    "prophetx": 0.02,
    "prophetexchange": 0.02,
    "rebet_exchange": 0.02,
    "sporttrade": 0.0,  # spread-based, no commission on winnings
    "novig": 0.0,       # peer-to-peer, no commission
}


def effective_american(listed: int, bookmaker_key: str) -> int:
    """Apply commission-on-winnings to a listed American price and return the
    rounded net American price. Standard books (no commission) return the
    listed price unchanged."""
    commission = BOOK_COMMISSION.get(bookmaker_key, 0.0)
    if commission <= 0:
        return listed
    # Payout multiplier on a $1 bet (what bettor wins on a win)
    m = listed / 100.0 if listed > 0 else 100.0 / -listed
    m_net = m * (1.0 - commission)
    if m_net >= 1:
        return round(m_net * 100)
    if m_net <= 0:
        return 0
    return -round(100 / m_net)
