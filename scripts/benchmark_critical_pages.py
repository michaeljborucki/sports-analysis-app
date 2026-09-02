"""Read-only latency benchmark for the application's critical pages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:8000"
ENDPOINTS = (
    ("health", "/api/health"),
    ("edges-arb", "/api/arbitrage"),
    ("edges-low-hold", "/api/low-hold?max_hold_pct=2.5"),
    ("edges-ev", "/api/ev?min_ev=1&max_longshot_odds=800"),
    ("edges-free-bets", "/api/free-bets"),
    ("edges-profit-boost", "/api/profit_boost"),
    ("accounts", "/api/coral33/accounts"),
    ("accounts-history", "/api/coral33/accounts/history?weeks=12"),
    ("systems", "/api/systems?timeframe=today"),
    ("odds-mlb", "/api/odds/mlb"),
)


@dataclass(frozen=True)
class Measurement:
    endpoint: str
    status: int
    seconds: float
    response_bytes: int


def format_measurements(measurements: list[Measurement]) -> str:
    lines = ["endpoint\tstatus\tseconds\tbytes"]
    lines.extend(
        f"{item.endpoint}\t{item.status}\t{item.seconds:.3f}\t{item.response_bytes}"
        for item in measurements
    )
    return "\n".join(lines)


def measure(name: str, endpoint: str, timeout: float = 30.0) -> Measurement:
    started = time.perf_counter()
    try:
        with urlopen(f"{BASE_URL}{endpoint}", timeout=timeout) as response:
            body = response.read()
            status = response.status
    except HTTPError as exc:
        body = exc.read()
        status = exc.code
    except (TimeoutError, URLError):
        body = b""
        status = 0
    return Measurement(name, status, time.perf_counter() - started, len(body))


def main() -> None:
    health = measure(*ENDPOINTS[0])
    edge_endpoints = ENDPOINTS[1:6]
    with ThreadPoolExecutor(max_workers=len(edge_endpoints)) as pool:
        edge_results = list(pool.map(lambda args: measure(*args), edge_endpoints))
    remaining = [measure(*item) for item in ENDPOINTS[6:]]
    results = [health, *edge_results, *remaining]
    print(format_measurements(results))
    print(json.dumps({"edge_burst_seconds": max(r.seconds for r in edge_results)}))


if __name__ == "__main__":
    main()
