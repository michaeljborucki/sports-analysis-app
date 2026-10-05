# VSiN MLB trends — candidate-system analysis

Date: 2026-09-10. Source: VSiN starter/bullpen correlation systems, MLB
series systems, extreme-stats systems, team-strength systems (Steve Makinen).
Third companion to the CFB and NFL analyses of the same date. Nothing
implemented.

## Scoring MLB differently — and a correction that matters

The CFB and NFL documents scored ATS records against a fixed 52.38%
break-even. **That method is wrong for MLB**, where every system here is a
moneyline play at wildly varying prices. A 44.4% win rate can be profitable
and a 55% win rate can be a loss; only ROI answers the question.

So these are scored on ROI with `t = ROI x sqrt(n)`, treating the standard
deviation of a one-unit moneyline bet as ~1.0. That understates SD on heavy
favorites and overstates it on big dogs, so t here is a rough ranking device.

**The correction, which changes several verdicts: a "fade" system does not
inherit the backing side's ROI.** Six of these systems are published as
negative-ROI records with the instruction to bet the other side. But if
backing a side returns −6.3% and the vig-fair return is about −4%, that side
is only ~2.3pp worse than fair — so the other side is ~2.3pp *better* than
fair, i.e. about −1.7%. **Still a loser.** You have to beat the hold twice.

Rule of thumb used below, assuming a ~4% two-way MLB moneyline hold:

> **fade ROI ≈ |backing ROI| − 8pp**

A system must be published at worse than roughly −8% ROI before fading it is
even break-even. That single line disqualifies most of this article.

## Scoreboard

| System | n | Published ROI | Fade ROI | t |
|---|---:|---:|---:|---:|
| Series #5 — road dog +101..+187, series finale, ending a road trip | 904 | +9.6% | — | 2.89 |
| Team Strength #5 — Aug+, both teams ≥.580, fav −111..−175 | 81 | +24.1% | — | 2.17 |
| Series #12 — interleague finale, opp bullpen spent 5+ IP | 79 | +21.8% | — | 1.94 |
| Better-bullpen underdog (2025) | 952 | +6.2% | — | 1.91 |
| Big favs −190+, better pen, win pct +19% | 531 | +6.2% | — | 1.43 |
| Series #2 — series finale on a 3+ game losing streak | 994 | +3.5% | — | 1.10 |
| Series #4 — road dog +101..+187, series finale | 1889 | +1.6% | — | 0.70 |
| FADE elite SP + negative bullpen | 134 | −17.1% | **+9.1%** | 1.05 |
| FADE good pen + bad SP | 410 | −9.4% | +1.4% | 0.28 |
| FADE bad pen + bad SP | 415 | −8.4% | +0.4% | 0.08 |
| FADE worse pen, 3+ game losing streak | 464 | −6.3% | −1.7% | −0.37 |
| FADE worse pen, 3+ game win streak | 611 | −4.3% | −3.7% | −0.91 |
| FADE scored 9+ runs last game | 4342 | −6.3% | −1.7% | −1.12 |
| FADE worse pen, 2-game win streak | 1344 | −4.4% | −3.6% | −1.32 |
| FADE road team that scored ≤2 last game | 5185 | −5.2% | −2.8% | −2.02 |

Note the bottom two rows. "Road teams scoring ≤2 last game are 44.4%" over
**5,185 games** is the most impressive-looking line in the article and it is
a **losing bet in both directions** once the vig is paid twice. Same for the
"magic number 9" fade at n=4,342. These are the two biggest samples on offer
and neither is playable.

## Tier D — the entire bullpen section is proprietary

Every system in "STARTER/BULLPEN CORRELATION SYSTEMS" keys on **Steve
Makinen Bullpen Ratings** and **SM starting-pitcher ratings** — proprietary
numbers with published thresholds (>25, ≥10, ≤−10, "negative") that mean
nothing without the rating scale. Not reproducible. Same verdict as the CFB
Stability Scores.

That is six systems, including the two most attractive on paper: the
better-bullpen underdog (+6.2% on n=952) and the elite-SP/bad-pen fade
(+9.1% fade ROI).

We *could* substitute a public proxy — bullpen ERA/FIP/xFIP over a trailing
window from a free source — but that is **a different system wearing the same
name**, and it would need its own backtest before anyone bets it. Worth
considering as separate work; not worth pretending it is this system.

## Tier A — buildable now, zero new data

**Team Strength #5** — August or later, both teams ≥.580 win pct, back the
smaller favorite priced −111 to −175. 55-26 SU, +19.53u, **ROI +24.1%,
n=81, t=2.17.**

Every field already exists: `month` (`context.py:88`), `home_win_pct` /
`away_win_pct`, and both moneylines. This is a registry entry plus one
`_evaluate_rule` branch and nothing else. **Cheapest addition in any of the
three documents.**

Caveat stated plainly: n=81 with a +24% ROI is a small, heavily-mined sample.
It is worth adding because it costs nearly nothing, not because 24% is real.

## Tier B — buildable, small additions to the MLB context pass

**Series #2** — final game of a series, team on a 3+ game losing streak.
486-508, +34.75u, ROI +3.5%, n=994, t=1.10.

We already build `series_game_number` and `series_length` (MLB 7 and MLB 12
use both) and `away_losing_streak` (MLB 1). Needs the finale predicate
(`series_game_number == series_length`) and losing streak for both sides —
the latter comes from the same history pass at `context.py:1357`. Largest
usable sample in the MLB set, but a thin +3.5% edge.

**Series #5** — road underdog priced +101 to +187, final game of a series,
**and that series ends a road trip**. 422-482, +86.62u, ROI +9.6%, n=904,
**t=2.89 — the strongest MLB candidate.**

The road-trip predicate is the only real work: it means the team's *next*
game is at home, which requires a schedule lookahead rather than the
backward-looking history we build today. Doable from the MLB schedule feed,
but it is genuinely new plumbing.

Note **Series #4 is the same bet without the road-trip filter** (+1.6% ROI,
n=1889) — the filter is where all the profit lives. Build #5; skip #4, which
would mostly emit break-even signals and dilute the page.

**Series #12** — home favorite/pick'em, last game of an interleague series,
lost its last game, opponent's bullpen threw 5+ innings last game. 55-24 SU,
+17.25u, ROI +21.8%, n=79, t=1.94. Interleague is trivial (AL vs NL), "lost
last game" we have. **Opponent bullpen innings requires per-game pitching
lines from box scores** — a new feed for one n=79 system. Defer.

## Tier E — reject on merit

Both extreme-stats fades, per the vig correction above: fading a 9+ run game
(−1.7%) and fading a road team that scored ≤2 (−2.8%). Large samples,
negative expectation in both directions.

## Recommendation

Add **Team Strength #5** and **Series #2** now; add **Series #5** if we are
willing to build the schedule-lookahead field, which I would, since t=2.89 is
the best MLB number available and the field is reusable.

Skip the bullpen section (proprietary), Series #4 (subsumed), Series #12
(new feed, n=79), and both extreme-stats fades (dead after vig).

Free to evaluate — no Odds API spend, no `cache_mode` change, no placement
gate touched.

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
