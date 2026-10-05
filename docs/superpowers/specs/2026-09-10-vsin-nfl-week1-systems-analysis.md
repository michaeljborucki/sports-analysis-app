# VSiN NFL Week 1 trends — candidate-system analysis

Date: 2026-09-10. Source: VSiN "AJ's Angles" + "NFL Week 1 Systems"
(Steve Makinen / AJ Makinen). Companion to
`2026-09-10-vsin-week2-systems-analysis.md` (CFB). Nothing implemented; this
is triage against `server/systems/`.

Same scoring method: win rate vs the -110 break-even of 52.38%, pushes
dropped from n, `z = (p - 0.5238) / sqrt(0.25/n)`.

## Scoreboard

| System | n | Win% | Edge | z |
|---|---:|---:|---:|---:|
| Sys3 — W1 road team that won 4-6 games prior yr | 80 | 70.0% | +17.6 | 3.15 |
| Sys2 — FADE W1 non-conf home team priced +3/-3 | 20 | 85.0% | +32.6 | 2.92 |
| W1 dogs of 6.5+ (AJ #1 = System 4) | 45 | 71.1% | +18.7 | 2.51 |
| Sys1 — divisional home underdogs, W1 | 34 | 73.5% | +21.1 | 2.47 |
| Vet QB, new team, road dog ≤5.5 | 72 | 66.7% | +14.3 | 2.42 |
| Sys12b — same games as Sys12, UNDER | 39 | 71.8% | +19.4 | 2.42 |
| Sys5 — W1 home fav hosting >.500 prior yr | 84 | 64.3% | +11.9 | 2.18 |
| Sys9 — <20 PPG allowed prior yr | 40 | 67.5% | +15.1 | 1.91 |
| Sys10 — turnover diff −0.9 or worse prior yr | 19 | 73.7% | +21.3 | 1.86 |
| Sys11 — 8+ close losses prior yr | 19 | 73.7% | +21.3 | 1.86 |
| FADE retread head coach, non-conference | 54 | 64.8% | +12.4 | 1.83 |
| Sys12 — dropped 5+ wins prior yr | 39 | 66.7% | +14.3 | 1.78 |
| FADE DK 77%+ handle on a favorite of 6.5+ | 38 | 65.8% | +13.4 | 1.65 |
| Sys6 — divisional road/neutral dogs ≤6.5 | 34 | 64.7% | +12.3 | 1.44 |
| Sys8 — FADE team that averaged 26+ PPG prior yr | 68 | 60.3% | +7.9 | 1.31 |

## Read the z-scores skeptically here — more so than in the CFB document

The NFL list looks *much* stronger than the CFB list (six candidates past
z=2, versus four). That is mostly an artifact, for three reasons.

**1. Week-1-only systems have tiny per-season samples.** System 2 is 20
games across 11 seasons — under two qualifying games a year. An 85% win rate
on n=20 is what threshold-mining looks like, not what a durable edge looks
like. The systems with the most credible construction (Sys3 at n=80, Sys5 at
n=84) are also the ones with the *lowest* headline percentages. That ordering
is the tell.

**2. The systems are not independent — they are the same handful of games,
counted repeatedly.** Cleveland +8.5 is a "play" in AJ #1, System 3, and
System 4, and System 8's fade of Jacksonville is that same bet a fourth time.
Arizona +9.5 appears in Systems 4, 11, and 12. Backing "five systems" on this
slate is placing roughly two independent bets at four times the intended
stake. **Any portfolio built from these needs signal de-duplication by
(event, side), not by system count** — our `WagerCandidate` model already
groups by supporting system, which handles this correctly if we surface stake
off the deduped wager rather than off the signals.

**3. The systems contradict each other on this very slate**, which means at
least some are noise by construction:

| Game | Says PLAY | Says FADE |
|---|---|---|
| SEA -3 vs NE | System 5 | System 2 |
| JAX -8.5 vs CLE | System 9 | System 8 (+ AJ #1, Sys 3, Sys 4 on CLE) |
| DET -7 vs NO | System 12 | System 8 (+ Sys 3, Sys 4 on NO) |

Three of the eight Week 1 games carry directly opposed signals from the same
author in the same article. These were mined one at a time and never
reconciled into a portfolio. Ours would have to reconcile them — which is an
argument for implementing a *few* of them, not all.

**4. Every one of these fires one Sunday per year.** Seven "systems" that
produce three to six signals each September is a thin return on build effort,
judged on its own. The case for building rests on the shared loader below,
which is reusable well beyond Week 1.

## Tier A — buildable today, zero new fetches

`nfl_scoreboard_context` (`context.py:540`) already supplies `week`,
`season_type`, `is_divisional`, and the odds feed supplies spreads. These
need nothing else:

- **System 1** — divisional home underdogs in Week 1 (73.5%, n=34).
- **System 4 / AJ #1** — Week 1 underdogs of 6.5+ (71.1%, n=45).
- **System 6** — divisional road/neutral underdogs of ≤6.5 (64.7%, n=34).
  Note this is a superset overlapping System 1's inverse; check for
  double-counting before shipping both.

**System 2** (fade a Week 1 non-conference home team priced +3 to −3) needs
one field we don't build: AFC/NFC. We already fetch every team's ESPN team
payload for its division (`context.py:1120`, 7-day cached), and the
conference is that group's parent — so this is a few lines on a request we
already make, not a new feed. But n=20; I would build the field and *not*
enable the system.

## Tier B — one new loader unlocks seven systems

Systems 3, 5, 8, 9, 11, 12 and 12b all need **prior-season team results**:
final wins, points scored/allowed per game, count of losses by ≤8, and
win-total change year over year. Every one of those is derivable in a single
pass over the prior regular season's scoreboard — and `_completed_results()`
(`context.py:359`) is already sport-agnostic and already does exactly this
pass for college football.

So this is one new fetch (prior-season NFL scoreboard, cached long like the
existing `nfl:playoffs:{season}` entry, which caches for 10 years) plus a
derivation function. That single loader:

- unlocks Systems 3, 5, 8, 9, 11, 12, 12b;
- **also produces NFL previous-game context**, which is half of what disabled
  **Football 13** needs (`registry.py:75`). Football 13's other half — the
  prior game's closing *total* — stays blocked on line history (see the CFB
  document's Tier C).

That reuse is the real argument for this work. As Week-1 systems alone it
would not be worth it.

**System 10** (turnover differential −0.9 or worse) is the exception:
turnovers are not in scoreboard payloads. It needs ESPN's team season-stats
endpoint — a separate feed for a single n=19 system. Skip.

## Tier C — blocked, no source

- **Veteran QB in his first season with a new team, road dog ≤5.5** (66.7%,
  n=72, z=2.42) — statistically the most interesting blocked candidate.
  Needs starting-QB identity plus tenure/transaction history. ESPN publishes
  depth charts but not reliably enough to key a bet on, and "veteran" is
  undefined in the source. Would need a curated list maintained by hand each
  season.
- **Retread head coaches in non-conference matchups** (64.8% fading, n=54) —
  needs a coach directory *with career history*. Our coach data is a
  hardcoded one-off scrape of a single team page for John Harbaugh
  (`context.py:1180`), built for Football 7. Same blocker as the CFB
  new-head-coach system.
- **DK 77%+ handle on favorites of 6.5+** (65.8% fading, n=38) — no betting
  splits source. Consistent with the CFB document: we cannot build any splits
  system.

## Tier D — reject on merit

- **Ravens-Colts UNDER 13-2** — head-to-head series trend, n=15.
- **Denver 8-1 UNDER on Monday night** — single-team situational trend, n=9.

Same standing policy as the CFB document: the registry takes systems, not
team or series trends.

## Recommendation

1. **Build the prior-season NFL results loader** (Tier B). It is the only
   item here that pays for itself beyond Week 1, because it also supplies NFL
   previous-game context for Football 13 and for any future in-season NFL
   system.
2. Off that loader, enable **System 3** (n=80, z=3.15) and **System 5**
   (n=84, z=2.18) — the two largest, least-mined-looking samples.
3. From Tier A, enable **System 4 / AJ #1** (n=45). Cheap, and it is the
   Week 1 angle with the most independent corroboration in the article.
4. Add the AFC/NFC field while touching the team payload, but leave System 2
   (n=20) disabled.
5. **Before enabling more than one of these, add signal de-duplication by
   (event, side)** so three systems naming Cleveland +8.5 read as one wager,
   not three.

Skip Systems 6, 8, 10, 12b-as-a-separate-system, all of Tier C, and all of
Tier D.

Everything recommended is free to evaluate — ESPN endpoints, already-cached
odds. No Odds API spend, no `cache_mode` change, no placement gate touched.

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
