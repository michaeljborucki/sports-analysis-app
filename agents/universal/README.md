# Universal agent rules

Sport-agnostic behaviors that should run **identically for every sport**.

The `agents/` tree is one self-contained package per sport (`baseball-agents/`,
`nba-agents/`, …), each evolving independently per `agents/FRAMEWORK.md`. Two
kinds of logic live there:

- **Per-sport rules** — edge thresholds, bet filters, scrapers, ensemble
  members, result-grading. These differ per sport and stay in the sport's repo
  (`<sport>-agents/config.py`, `scrapers/`, etc.).
- **Universal rules** — behavior that shouldn't drift between sports. Instead of
  copy-pasting it into every repo, it lives here once and each sport opts in.

A universal rule never imports anything sport-specific. It takes the sport's
per-game work (and, where relevant, its alert sender) as callables and supplies
only the shared orchestration around them.

## Rules

| Rule | Module | What it does |
|---|---|---|
| Priority alerts | `priority.py` | Sort games soonest-first, analyze in parallel, and fire each game's alert the moment it finishes — never batch all alerts until the slate is done. |

## How a sport opts in

Each sport package is its own import root (it runs with its directory on
`sys.path`), so a sport adds the shared `agents/` directory to the path and
imports the rule:

```python
import os, sys
_AGENTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../agents
if _AGENTS_ROOT not in sys.path:
    sys.path.append(_AGENTS_ROOT)

from universal.priority import run_priority_pipeline
```

Then it hands the rule its own per-game function and alert sender. See
`baseball-agents/main.py` and `soccer-agents/main.py` (the `daily` command) for
the reference wiring.

### Adoption status

| Sport | State |
|---|---|
| baseball | ✅ wired to `run_priority_pipeline` |
| soccer | ✅ wired to `run_priority_pipeline` (whole-night slate, sorted by kickoff) |
| tennis | ✅ already conforms (bespoke: time-sorts flagged matches + per-match alerts) |
| ncaab, nba, cricket, ufc, esports | ⏳ no `notify/` module yet — adopt the immediate-alert half once alerting exists; process the slate soonest-first in the meantime |

A sport can only do the *immediate-alert* half once it has a `notify/` module.
Until then it should at least analyze the slate soonest-first so the closest
games are handled first.

## Tests

```bash
python -m pytest agents/universal/tests
```

These have no sport dependencies, so they run standalone from the repo root.
