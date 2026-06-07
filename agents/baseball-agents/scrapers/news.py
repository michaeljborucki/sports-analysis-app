import requests
from config import MLB_API_BASE


def get_injuries(team: str = None) -> list[dict]:
    """Get current injury list from MLB Stats API."""
    try:
        url = f"{MLB_API_BASE}/injuries"
        params = {"sportId": 1}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[injuries] API error: {e}")
        return []

    injuries = []
    for person in data.get("people", []):
        team_abbrev = person.get("currentTeam", {}).get("abbreviation", "")
        if team and team_abbrev != team:
            continue

        for injury in person.get("injuries", []):
            injuries.append({
                "player": person["fullName"],
                "team": team_abbrev,
                "injury": injury.get("description", ""),
                "status": injury.get("status", ""),
            })

    return injuries


def get_transactions(team_id: int = None, days: int = 3) -> list[dict]:
    """Get recent transactions from MLB Stats API."""
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=days)

    url = f"{MLB_API_BASE}/transactions"
    params = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    }
    if team_id:
        params["teamId"] = team_id

    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "date": t.get("date", ""),
                "type": t.get("typeDesc", ""),
                "description": t.get("description", ""),
            }
            for t in data.get("transactions", [])
        ]
    except Exception:
        return []
