# VSiN Week 2 CFB trends — candidate-system analysis

Date: 2026-09-10. Source: VSiN "Week 2 College Football Betting Trends"
(Steve Makinen / AJ Makinen). Nothing here is implemented; this is a triage
of ~29 published angles against our `server/systems/` framework.

## Method

Every claim is scored two ways.

1. **Edge quality.** Win rate vs the -110 break-even of 52.38%, with pushes
   dropped from n, and a z-score for "how far past break-even, given n".
   `z = (p - 0.5238) / sqrt(0.25/n)`.
2. **Feasibility.** What context fields the rule needs vs what
   `server/systems/context.py` builds today.

**Selection-effect warning, applies to the whole document.** These are
*published* trends, chosen by the author because they look good, with
thresholds that were tuned to the data (52-point line swings, 735 yards,
19.5-point favorites, 58 points scored). Across 29 candidates you would
expect ~1.5 to clear z=2 by chance alone — and exactly 4 do. Treat z as a
*ranking* device, not as proof. Nothing below should go live without our
own backtest, and every one of them is public information already priced by
the market to some degree.

## Scoreboard

| System | n | Win% | Edge | z |
|---|---:|---:|---:|---:|
| Two ranked teams, home side (since 2017) | 327 | 58.7% | +6.3 | 2.29 |
| Line swing ≥52 worse in Game 2 | 63 | 66.7% | +14.3 | 2.27 |
| DK: non-conf OVER <55 total, 80%+ handle | 96 | 63.5% | +11.2 | 2.19 |
| FADE team that lost as a 19.5+ favorite | 110 | 62.7% | +10.3 | 2.17 |
| Unranked road, within 7 of ranked → UNDER | 149 | 60.4% | +8.0 | 1.96 |
| Ranked off close win w/o cover, now favored | 274 | 57.7% | +5.3 | 1.75 |
| Scored 58+ while allowing <10 → next game | 264 | 57.2% | +4.8 | 1.57 |
| DK: non-conf UNDER, total 55+ | 74 | 60.8% | +8.4 | 1.45 |
| Revenge vs defense allowing 35+ PPG | 412 | 55.8% | +3.4 | 1.40 |
| FADE blowout-vs-spread by 38+ (both sides) | 345 | 55.9% | +3.6 | 1.32 |
| Stability edge 6+, non-conf, Weeks 0–3 | 563 | 55.1% | +2.7 | 1.27 |
| FADE 735+ yards in prior game | 79 | 59.5% | +7.1 | 1.26 |
| FADE ranked off close loss vs unranked | 146 | 57.5% | +5.2 | 1.25 |
| FADE stability score 0–6, non-conf | 410 | 55.1% | +2.7 | 1.11 |
| 17+ returning starters, Weeks 0–3 | 200 | 56.0% | +3.6 | 1.02 |
| DK: total ≥59, majority handle UNDER | 118 | 56.8% | +4.4 | 0.96 |
| DK: total ≤49, 72%+ handle UNDER | 122 | 56.6% | +4.2 | 0.92 |
| DK: 68%+ handle on small home favs ≤7 | 150 | 56.0% | +3.6 | 0.89 |
| DK: huge home favs 27.5+, majority handle | 161 | 55.9% | +3.5 | 0.89 |
| FADE ≤100 yards in prior game | 61 | 57.4% | +5.0 | 0.78 |
| FADE line swing ≥52 *better* in Game 2 | 53 | 56.6% | +4.2 | 0.61 |
| FADE new head coach, Weeks 0–3 | 264 | 54.2% | +1.8 | 0.58 |
| DK: 55%+ of bets on road dogs | 288 | 53.5% | +1.1 | 0.37 |
| FADE new defensive coordinator | 379 | 53.3% | +0.9 | 0.36 |
| DK: 58%+ handle on road dogs | 292 | 52.7% | +0.4 | 0.12 |
| DK: FADE handle majority on road favs | 781 | 52.6% | +0.2 | 0.14 |
| **DK: FADE >75% handle side (flagship)** | 1269 | **52.5%** | **+0.1** | 0.07 |
| DK: FADE 76%+ of bets on home side | 520 | 51.5% | −0.8 | −0.38 |
| DK: non-Saturday betting majority | 532 | 54.9% | +2.5 | 1.16 |

Note the flagship DK splits system: 1,269 decisions at 52.5% is **exactly
break-even at -110**. The article calls it "a small profit in four straight
years"; on these numbers it is a coin flip that pays the vig. Its sibling
(#2, fade 76%+ of bets on home) is *below* break-even. The DK splits family
has the largest samples in the article and the smallest edges — good
evidence the public-fade angle is already priced.

## Tier A — buildable now, no new data source

Both use scoreboard results we already parse in `_completed_results()`
(`context.py:359`) and revenge machinery we already ship.

**A1. Revenge vs a defense allowing 35+ PPG** — 230-182 ATS (55.8%),
n=412, z=1.40. We already compute `home_revenge` / `away_revenge`
(`context.py:463`). The only new field is opponent points-allowed per game
to date, which is a sum over the same completed-results pass. Largest
sample of any Tier A/B candidate. Bet type: spread, back the revenge side.

**A2. Ride a 58+ point / <10 allowed performance** — 151-113 ATS (57.2%),
n=264, z=1.57. Needs the prior game's points scored *and* allowed; we
already store `*_previous_points` and could add `*_previous_points_allowed`
in `college_previous_game_context` (`context.py:411`) in one line — the
opponent entry is already in hand. **Cheapest system in the whole document
to build.**

Neither costs an Odds API request; ESPN's scoreboard is free and already
cached through `context_cache`.

## Tier B — buildable, needs a new free ESPN feed

**B1. AP-poll systems.** Three of the article's four ranked-team systems are
implementable off ESPN's free rankings endpoint plus data we already have:

- Two ranked teams, non-neutral, back the home side — 192-135-9 (58.7%),
  n=327, z=2.29. **Top-ranked candidate in the document.** Needs: rankings +
  `neutral_site` (have it).
- Unranked road team within 7 either way of a ranked team → UNDER —
  90-59 (60.4%), n=149, z=1.96. Needs rankings + spread + total (have both).
- FADE a ranked team off a ≤7-point loss facing an unranked team —
  62-84-4, so fading is 57.5%, n=146, z=1.25. Needs rankings +
  `*_previous_margin` (have it).

The fourth (ranked off a close win **that didn't cover**, now favored —
57.7%, n=274, z=1.75) needs the prior game's *spread*, which pushes it into
Tier C.

One new fetcher + cache entry unlocks three systems. Best
work-to-systems ratio here.

**B2. Yardage systems.** FADE 735+ yards in the prior game (59.5% fading,
n=79) and FADE ≤100 yards (57.4%, n=61) need team yardage from ESPN's
per-game summary endpoint — one request per completed game, not per
scoreboard, so meaningfully more fetching and caching than B1. Samples are
small and both z-scores are ~1.2. **Not worth the plumbing yet.**

## Tier C — blocked today, unblocked prospectively by `closing_lines`

Five candidates depend on knowing a **prior game's point spread**:

- Line swing ≥52 points worse in Game 2 → back that team — 42-21 (66.7%),
  n=63, z=2.27. Also published twice in the article (AJ's Angles + Game 2
  Reactionary #5).
- Line swing ≥52 points better → fade — 30-23, n=53, z=0.61. Weak; skip
  even when unblocked.
- FADE a team that just lost as a 19.5+ favorite — 62.7% fading, n=110,
  z=2.17.
- FADE both sides of a game decided 38+ points away from the spread —
  55.9% fading, n=345, z=1.32.
- Ranked off a close win it didn't cover, now favored (B1's fourth) —
  57.7%, n=274, z=1.75.

`odds_snapshot` purges at 10 minutes (`server/odds/cache.py:93`), so we have
no line history. **But `closing_lines` (`cache.py:129`) is permanent and
sport-agnostic** — `clv_capture.py` freezes every event whose kickoff falls
in [now+5min, now+15min], across all sports. If the CFB scheduler is
fetching through the season with `cache_mode=live`, we accumulate exactly the
closing spread and total history these five rules need — going forward only,
never retroactively.

That makes this a **decision to make now, not later**: confirm CFB events are
actually landing in `closing_lines` this season, or the 2027 version of this
analysis is blocked all over again. Backfilling instead would mean the Odds
API historical endpoints (`server/odds/client.py:227`) — **metered spend,
your call, not something I'd trigger.**

## Tier D — permanently blocked (proprietary inputs)

- **Stability Scores** (edge 6+: 55.1%, n=563; fade 0–6: 55.1%, n=410) —
  Makinen's proprietary score. Not reproducible from public data. The
  underlying idea is public-ish (roster/staff continuity) but the score
  itself is the system.
- **Makinen Power / Effective Strength / Bettors Ratings** — proprietary
  projections. The "underpriced dog/favorite" lists are outputs of a model we
  don't have.
- **All 12 DK betting-splits systems** — require DraftKings handle and
  ticket-count splits, which we have no source for. Moot anyway: as shown
  above, the family's edges are ~0 at large n.
- **New defensive coordinator** (z=0.36) — ESPN publishes no coordinator
  data. Dead on both feasibility and merit.
- **New head coach** (z=0.58) — technically sourceable by diffing coach
  identity season-over-season, but our coach data is a hardcoded one-off
  (`context.py:1180` scrapes a single team page for John Harbaugh, for
  Football 7). Building a real coach directory to power a z=0.58 system is
  not worth it.
- **17+ returning starters** (56.0%, n=200, z=1.02) — returning-starter
  counts are hand-curated preseason data, no free feed.

## Tier E — reject on merit, regardless of feasibility

**Single-team situational trends** (~45 of them: "PURDUE is 7-20 ATS at
home", "UMASS is 0-8 ATS as a favorite", "NAVY 32-11 in conference off a
home win"). Samples of 20–70, one team, no mechanism, and they are the
purest form of the multiple-comparisons problem — with 136 FBS teams ×
a dozen splits, some team is always 0-8. They also need full per-team ATS
history (Tier C data). **Recommend a standing policy: our registry takes
systems, not team trends.**

**Head-to-head series trends** ("Road teams 7-1 ATS in the last eight of
Bama-UK"). n=6–8. Noise by construction. Same rejection.

**CFB Game 2 Reactionary #3** (double-digit conference favorite in Game 2
after an FCS opener: 2-10 ATS). n=12. Sample too small to act on regardless
of how bad it looks.

## Already implemented — refresh, don't add

Two of the article's Game 2 systems are systems we already ship, with
records now one season longer:

| Article | Ours | Their record | Our stored claim |
|---|---|---|---|
| Reactionary #2 — FBS loss in G1, favored 24+ over FCS in G2 | Football 22 (`FOOTBALL_22_CFB_GAME2_FCS_REBOUND_FADE`) | 50-71-2 (41.3%) | 48-71-2 (40.3%) |
| Reactionary #4 — scored ≤10 in a 17+ point opening loss, home in G2 | Football 23 (`FOOTBALL_23_CFB_GAME2_HOME_SHUTDOWN_OFFENSE_FADE`) | 49-63-2 (43.8%) | 48-63-2 (43.2%) |

Worth confirming our captured *rules* match theirs (their #2 names a
"favored ≥24" threshold; check ours does too) and updating the
`source_claim` strings in `registry.py`.

## Recommendation

Build in this order:

1. **B1 — AP-poll rankings feed** → three systems, one new fetcher, the
   highest-z candidate in the document (n=327). Start here.
2. **A2 — points allowed in the prior game** → one system, roughly a
   one-line context change.
3. **A1 — opponent PPG allowed + revenge** → one system, largest sample of
   the free-data candidates.
4. **Tier C decision** — verify CFB closing lines are accumulating now, so
   the five line-history systems become buildable next season without paid
   backfill.

Skip B2, D, and E entirely.

Everything in steps 1–3 is free to evaluate (ESPN endpoints, already-cached
odds) and none of it touches `cache_mode` or any placement gate.

---

## Shipped 2026-09-10

Implemented and LIVE on `/api/systems` and the systems page — not
flag-gated, no new enable switch. The registry went from 36 primary systems
to 53: 18 added, Football 11 deleted (48.2% ATS one way, 51.8% the other —
no playable side), Football 22/23 source claims refreshed. Football 8 and
Football 13 remain the only disabled entries.

Blast radius: `server/systems/` only. The EV, arbitrage, low-hold and props
scanners are untouched, no placement path changed, `cache_mode` untouched,
and every new context fetch is a free ESPN/MLB endpoint — no Odds API spend.
