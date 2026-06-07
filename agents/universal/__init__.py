"""Universal agent rules — sport-agnostic behaviors shared across every sport.

The `agents/` tree holds one self-contained package per sport (``baseball-agents``,
``nba-agents``, …). Logic that should behave identically for *every* sport lives
here instead of being copy-pasted into each repo. A per-sport pipeline opts into a
universal rule by importing it and feeding in its own per-game work.

See ``agents/universal/README.md`` for the per-sport vs universal split and how a
sport wires itself in.

Current rules:
  - ``priority`` — analyze games soonest-first and alert the moment each game
    finishes, instead of batching all alerts until the whole slate is done.
"""
from universal.priority import run_priority_pipeline, sort_by_first_pitch

__all__ = ["run_priority_pipeline", "sort_by_first_pitch"]
