"""One-shot: pull placement entries out of the dev HAR and scrub secrets.

Reads ~/Downloads/coral33.com.har, pulls the five parlay-placement entries
identified by entry index, scrubs JWT + customer-specific tokens, and
writes JSON fixtures under server/tests/fixtures/coral33/placement/."""
from __future__ import annotations

import json
import re
from pathlib import Path


HAR = Path.home() / "Downloads/coral33.com.har"
OUT = Path("server/tests/fixtures/coral33/placement")

# entry_index -> fixture name (verified against HAR run on 2026-06-21)
ENTRIES = {
    36: "get_parlay_specs",
    37: "get_info_parlay",
    40: "check_wager_line_multi_parlay",
    41: "insert_wager_parlay",
    44: "get_pending_by_ticket",
}

# Sanity-check: each entry's URL must contain the expected operation name.
# Guards against HAR drift if the capture is re-taken with a different
# click sequence and entry indices shift.
EXPECTED_OPS = {
    36: "getParlaySpecs",
    37: "getInfoParlay",
    40: "checkWagerLineMulti",
    41: "insertWagerParlay",
    44: "getPendingByTicket",
}


def scrub_jwt(obj):
    """Recursively replace anything that looks like a JWT with a placeholder."""
    if isinstance(obj, str):
        # Loose JWT pattern: three base64url chunks separated by dots
        return re.sub(
            r"eyJ[A-Za-z0-9_\-=.]+\.[A-Za-z0-9_\-=.]+\.[A-Za-z0-9_\-=.]+",
            "<REDACTED_JWT>", obj,
        )
    if isinstance(obj, dict):
        return {k: scrub_jwt(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_jwt(v) for v in obj]
    return obj


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    har = json.loads(HAR.read_text())
    entries = har["log"]["entries"]
    for idx, name in ENTRIES.items():
        e = entries[idx]
        url = e["request"]["url"]
        expected = EXPECTED_OPS[idx]
        if expected not in url:
            raise SystemExit(
                f"HAR entry {idx} URL {url!r} does not contain expected "
                f"operation {expected!r}; HAR may have changed shape - "
                f"re-capture or update ENTRIES indices."
            )
        request_body = e["request"].get("postData", {}).get("text", "")
        request_json = json.loads(request_body) if request_body else None
        response_body = e["response"]["content"].get("text", "")
        response_json = json.loads(response_body) if response_body else None
        out = {
            "url": url,
            "request": scrub_jwt(request_json),
            "response": scrub_jwt(response_json),
        }
        (OUT / f"{name}.json").write_text(
            json.dumps(out, indent=2, sort_keys=False) + "\n"
        )
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
