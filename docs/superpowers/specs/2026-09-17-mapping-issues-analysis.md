# Mapping issues — analysis (2026-09-17)

Read-only audit. **No code, config, or data was changed.** Sources: `server/cache.mapping.sqlite`
(the live mapping-health table, last audit 17:57 MT), `server/cache.db`,
`/Users/mikeborucki/personal_workspace/betting-db/data/odds.db` (read-only), and the code.

## What the table is

`server/odds/mapping_health.py` runs a 60s audit (`main.py:188`), exposed at `/api/mapping-health`
and `/settings/mapping-health`. It is **diagnostics only** — `candidates` are never fed back into
matching (proved: `candidates` is written to SQLite and read only by `listing()`; the alias TOML is
opened read-only at `player_names.py:156`; no POST route touches mapping health).

Two kinds matter:
- `team` — a Coral33 event that never joined an Odds API event. **Every Coral33 price on that event
  is dropped from EV / arbitrage / low-hold entirely.** This is the money-losing class.
- `player_name` / `player_coverage` — prop-level name splits and orphans.

## Volume

2,908 issues, 1,805 unresolved, 510,555 total hits. ~290 new issues/day, no purge.
77% of rows (2,239) are stale >2 days and can never resolve.

Live today (`last_seen >= 2026-09-17`): **54 unresolved team, 9 player_coverage.**

| sport | open today | hits today | Coral33 events that DID land |
|---|---|---|---|
| ufc | 3 | 20,438 | 11 |
| soccer | 25 | 17,030 | 86 |
| boxing | 3 | 5,214 | 2 |
| tennis | 20 | 4,970 | 4 |
| asian_baseball | 3 | 234 | 7 |

Hit counts are inflated: an issue is re-recorded every fetch cycle until kickoff, so 6,908 hits
≈ one fixture observed for four days, not 6,908 distinct failures.

---

## Finding 1 — Tennis: a ±15-minute match window, not a naming problem (biggest fixable loss)

377 unresolved rows / 79k hits. Tennis lands only **4 events** in the snapshot against 20 open
mismatches today.

`_normalize_team` already reduces both sides to `<initial> <surname>`
(`server/odds/books/coral33/event_matcher.py:102-104`, from commit 337ad91), verified:

```
F Tiafoe | Frances Tiafoe -> 'f tiafoe' == 'f tiafoe'   True
A Sabalenka | Aryna Sabalenka -> 'a sabalenka' == 'a sabalenka' True
```

The names match. The **times** don't:

| Coral33 | Odds API | delta | window |
|---|---|---|---|
| F Tiafoe / B Shelton 09-11T12:00:01Z | 09-11T23:05:00Z | 11h05m | ±15 min |
| A Sabalenka / E Rybakina 09-12T12:00:01Z | 09-12T20:15:01Z | 8h15m | ±15 min |
| C Gauff / E Rybakina 09-11T00:30:01Z | 09-11T00:55:11Z | 25 min | ±15 min |

Two modes: a `12:00:01Z` placeholder/TBD timestamp (41 of 377 unresolved rows sit at exactly
`12:00:01`; **zero resolved rows do**), and 20-40 min schedule drift.

`SPORT_WINDOW_MINUTES` (`event_matcher.py:20-25`) has entries for ncaaf (30), ufc (360), boxing (360)
— **no tennis entry**, so tennis falls through to `MATCH_WINDOW_MIN = 15` (`event_matcher.py:13`).

Smoking gun: `A Parks / S Bejlek` is unresolved at `12:00:01` and resolved at `20:30:01` — same pair,
same day.

Fix shape: a tennis entry in `SPORT_WINDOW_MINUTES`, or reuse the date-anchored approach already
built for the Odds API side (`server/odds/books/_anchor_table.py`, roadmap item M3).

## Finding 2 — UFC / boxing: card-date rollover + empty alias tables

Both sports are fetched (`sports.py:214-238`; betting-db holds 150 MMA and 134 boxing events) and
matched with a generous ±360 min window. The failures split three ways:

| Coral33 | Odds API | delta | cause |
|---|---|---|---|
| Merab Dvalishvili / Petr Yan 10-24T14:00 | 10-25T03:30 | 13h30m | time only (names equal) |
| Movsar Evloev / Alexander Volkanovski 10-24T14:00 | 10-25T04:00 | 14h | time + `alexander` vs `alex` |
| Doo Ho Choi / Patricio Pitbull | `Dooho Choi` | 5h15m (inside window) | **name only** |
| Rongzhu / Rafa Garcia | `Zhu Rong` | 1 min | **name only** (reversed transliteration) |
| Meiirim Nursultanov / Jesus Ramos | `Jesus Alejandro Ramos Jr` | 0 min | **name only** |
| Lucas Bahdi / Floyd Schofield 10-11T03:00 | `Floyd Scholfield` 10-10T03:00 | exactly 24h | time + misspelling |
| Oscar Collazo / Ricardo Sandoval 10-11T02:00 | `Ricardo Rafael Sandoval` 10-10T02:00 | exactly 24h | time + name |
| Tommy Gantt / Drakkar Klose | — | — | genuine Odds API coverage gap |

The 13-14h and exactly-24h offsets are systematic Coral33 card-date/rollover errors, not jitter —
a 24h-tolerant combat-sport match (fights are unique by fighter pair) would close them.

`[team_aliases.ufc]`, `[team_aliases.boxing]` and `[team_aliases.tennis]` (`coral33.toml:547-556`)
are **empty comment-only stubs**, and these sports have no prefix fallback
(`_PREFIX_MATCH_SPORTS = {"baseball_ncaa", "ncaaf"}`, `event_matcher.py:274`).

## Finding 3 — Soccer: 91% league-coverage gap, 9% real alias bugs

115 unresolved / 325k hits — the largest block, but mostly not a bug.

Coral33 pulls `"ARG PRI DIV"` (`coral33.toml:132`) and a `"JAP J LEA"` subtype that also carries
other Asian leagues. `sports.py:259-282` requests 13 soccer keys and **Argentine Primera, Saudi,
UAE and K-League are not among them**. Those fixtures can never match.

| bucket | issues | hits | requested? |
|---|---|---|---|
| Argentina (Primera + Primera Nacional) | 65 | 178,456 | no |
| Gulf (Saudi / UAE) | 21 | 79,504 | no |
| Korea (K-League) | 8 | 18,016 | no |
| Japan (incl. J2) | 6 | 12,740 | J1 only |
| covered leagues (Serie A / La Liga / EPL / Ligue 1 / MLS / Liga MX) | 15 | 36,606 | yes |

Cross-checked against `closing_lines`: both clubs known to the Odds API in only **8 of 115** rows;
the exact fixture present in **1 of 115**.

The real bugs inside the covered slice:

**3a — 21 of 136 soccer alias keys are unreachable.** `_normalize_team` strips accents and
punctuation *before* the dict lookup (`event_matcher.py:78-82,105`), but `mapping.py:143-146` loads
TOML keys **raw**. Any key with an accent or punctuation is dead: `club américa`, `américa`,
`bayern münchen`, `atlético madrid`, `man. city`, `man. united`, `nott'm forest`, `paris s.g.`,
`d.c. united`, `brighton & hove albion`, … This directly causes `Club America / Cruz Azul` (6,724
hits) and `Guadalajara / Club America` (1,804 hits). NBA/NHL/MLB/NCAAF tables have zero unreachable
keys — soccer-only.

**3b — 6 plainly missing aliases:** `Seattle Sounders`→`Seattle Sounders FC`, `Orlando City`→`…SC`,
`St. Louis City`→`…SC`, `Sanfrecce Hiroshima`→`Hiroshima Sanfrecce FC`, `Chiba`→`JEF United Chiba`,
`Urawa Reds`→`Urawa Red Diamonds`.

**3c — no soccer time window.** `Atlas / Toluca` orphaned on a 115-minute kickoff delta (Liga MX
kickoff times disagree ~2h between sources) against the ±15 min default.

`Juventus / Sassuolo` is neither: no such event exists on the Odds API side that weekend, and
Coral33 listed the fixture **twice at different kickoffs** — a Coral33 schedule artifact.

## Finding 4 — Player props: hand-maintained aliases, and the fix isn't committed

**Class A (`player_name`, 38 unresolved)** is almost entirely generational suffixes:
`Kenneth Walker`/`walker iii`, `Marvin Mims`/`mims jr`, `Vladimir Guerrero`/`guerrero jr`,
`Fernando Tatis`/`tatis jr`, `Michael Pittman`, `Luther Burden`, plus typos (`Corbin Carrol`,
`Merril Kelly`, `Christian Javier`, `Zac Thornton`).

`_fold` deliberately does **not** strip `jr/sr/ii/iii` — `test_player_names.py:64-65` asserts
`"Jaren Jackson Jr." -> "jaren jackson jr"`, and `test_mlb_player_aliases.py:13` explicitly asserts
the suffix forms must stay distinct under `nfl`. Rationale: Luis Garcia the pitcher vs Luis Garcia Jr.
the batter. So bridging is per-sport alias data by design.

But the maintenance loop is not keeping up: `player_aliases.toml` has **17 entries total**
(nba 5, mlb 9, mlb_batter 1, wnba 1, nfl 1; nhl/soccer/tennis empty) and **one commit in 223**.
Everything since is uncommitted working-tree edits — the current diff adds the 6 MLB suffix aliases,
the whole `[mlb_batter]` table and the `[nfl] andy borregales` row. **Those fixes exist only in your
working tree.** Also `reload_aliases()` exists but nothing calls it — a new alias needs a server restart.

**Class B (`player_coverage`, 1,196 unresolved, mlb `batter_total_bases` alone 656 issues / 15,267
hits) is not a name bug.** `kind` is assigned purely by whether fuzzy matching found anything
(`mapping_health.py:102-104`); if no other book posted that market for that event, `others` is empty
and every Coral33 player becomes a row. Two causes: the props tier is window-gated at
`games_window_hours = 6` (`markets.mlb.toml:66`, `fetcher.py:525-529`) while Coral33 posts its whole
board, and Coral33's player list is simply deeper (204 distinct `batter_total_bases` names).
Confirmed in the snapshot: **100% of `player_*`/`batter_*`/`pitcher_*` rows are coral33-only.**
No alias will ever fix these; they should not share a queue with class A.

## Finding 5 — The health table itself distorts the picture

1. **Row explosion.** `identity = [kind, sport, source, event, raw_name, market]`
   (`mapping_health.py:46`) includes the Coral33 commence time and the raw name. Each Coral33 kickoff
   nudge mints a **new** row, and `resolved=1` only updates that exact identity — so drifted rows
   never close. `F Tiafoe / B Shelton` has six rows at `12:00:01, 23:30:01, 23:35:01, 23:40:01,
   23:42:01`. `Vladimir Guerrero` has six (one per event), `Kenneth Walker` three (one per market).
2. **`" Games"` rows are pure double-reporting.** Matching uses `_clean_team`'d names
   (`normalizer.py:153-154,177`) but `report_issue` passes the **raw** strings
   (`normalizer.py:191-193, 201-203`). `F Tiafoe / B Shelton` and `F Tiafoe Games / B Shelton Games`
   both show 1,888 hits at the same event — identical failure, two rows. Tennis counts are ~2x inflated.
3. **`" 1st Set"` is a real bug, not a duplicate.** That suffix is absent from `_ALT_SUFFIXES`
   (`normalizer.py:56-64`), so `"F Tiafoe 1st Set"` reaches the matcher and normalizes to `'f set'`.
   Also `_clean_team` `break`s after the first suffix hit — only one suffix is ever stripped.
4. **`candidates=[]` means "no fixture within ±30 min", never "names too different."**
   `team_candidates` hard-codes 1800s (`mapping_health.py:126`) — **12x narrower than the UFC/boxing
   matcher's own ±360 min**. `"F Tiafoe / B Shelton"` vs `"Frances Tiafoe / Ben Shelton"` scores 0.833,
   far above the 0.55 cutoff; it shows [] only because of the time filter. The diagnostic is
   structurally blind exactly where the matcher is most permissive.
5. **The page truncates.** `listing()` caps at 1,000 rows ordered unresolved-first; with 1,805
   unresolved you never see resolved history, and 77% of what you do see is dead fixtures.
6. **Dead code:** `event_matcher`'s `window_minutes` constructor arg is stored at `:132` and never
   read — `match()` always uses the module table.

## False-positive warning

`difflib` at cutoff 0.65 produces confident nonsense: **`JJ McCarthy` -> `jake mccarthy`** (an NFL QB
suggested as an MLB outfielder) and `Marvin Harrison` -> `["marvin harrison jr", "omarion hampton"]`.
Nothing auto-applies these, but `player_aliases.toml:10-14` instructs the operator to copy from the
health page by hand with no roster check. "Apply the top suggestion" would be unsafe as written.

## Ranked fix list (none applied)

By money impact — each `team` row is a Coral33 event fully absent from the edge scanners.

1. **Tennis match window** (`SPORT_WINDOW_MINUTES`) — ~20 live events/day, currently 4 landing.
2. **UFC/boxing 24h card-date tolerance + 3 fighter aliases** — highest hits-per-issue in the table.
3. **Normalize alias keys at load** (`mapping.py:143-146`) — revives 21 dead soccer aliases.
4. **Add the 6 missing soccer aliases + a soccer time window.**
5. **Commit the working-tree `player_aliases.toml` edits** before they're lost; call `reload_aliases`
   on change so a new alias doesn't need a restart.
6. **Report cleaned names + bucket the commence time in `identity`**; strip `" 1st Set"`;
   widen `team_candidates` to the sport's own window; purge/archive rows past kickoff.
7. **Suppress issues for Coral33 leagues with no Odds API counterpart** (Argentina, Gulf, K-League,
   J2) — or add those league keys — so the table stops being 90% noise.

Items 1-4 change matching behavior (more Coral33 prices reach the scanners); items 5-7 are
diagnostics/hygiene only.

---

# Implemented 2026-09-17 (same day)

All seven ranked items, TDD'd in `server/tests/test_mapping_fixes.py` (49 tests).
**Everything below is LIVE** once the API restarts — none of it is flag-gated.

| # | Change | File |
|---|---|---|
| 1 | tennis window ±720 min, soccer ±180 min | `event_matcher.py` `SPORT_WINDOW_MINUTES` |
| 2 | ufc/boxing window ±1500 min (absorbs the exact-24h card rollover) | same |
| 2 | 3 UFC + 3 boxing fighter aliases | `coral33.toml` |
| 3 | alias keys **and values** folded through the matcher's own normalizer at load; collisions logged | `mapping.py` `_fold_alias_table` + `event_matcher.normalize_team_key` |
| 4 | 6 soccer aliases (Sounders/Orlando/St. Louis/Hiroshima/Chiba/Urawa) | `coral33.toml` |
| 5 | 19 confirmed prop aliases (5 NFL, 5 `[mlb_batter]`, 3 new `[mlb_pitcher]`) | `player_aliases.toml` |
| 5 | alias file hot-reloads on mtime (throttled to 30s) — no restart to add one | `player_names.py` `_get_aliases` |
| 6 | mapping-health identity buckets a team issue's kickoff to its UTC **date** | `mapping_health.py` `_identity_event` |
| 6 | orphans report the **cleaned** pair, so `" Games"` no longer double-counts | `normalizer.py` |
| 6 | `" 1st Set"` lines skipped explicitly, counted in the cycle log, never reported | `normalizer.py` `_UNSUPPORTED_SUFFIXES` |
| 6 | `team_candidates` window follows the sport instead of a flat ±30 min | `mapping_health.py` |
| 6 | `purge()` drops issues >3 days past their fixture; runs each audit tick | `mapping_health.py` |
| 7 | orphans split into `team` vs `team_coverage` (no club on the slate) | `mapping_health.classify_team_issue` + `fetcher.build_team_issue_reporter` |

## Verified against live data, not just tests

Replaying the 300 team orphans recorded since 2026-09-15 through the fixed
matcher and the real betting-db slate:

```
now MATCH        :  25   (were dropped from every scanner; now priced)
reclassified cov : 226   (uncovered competitions — out of the bug queue)
still unresolved :  44
```

Recovered fixtures include every top-hit offender: Evloev/Volkanovski,
Dvalishvili/Yan, Doo Ho Choi/Pitbull, Pantoja/Van, Bahdi/Schofield,
Nursultanov/Ramos, Collazo/Sandoval, Seattle Sounders/Colorado Rapids,
Guadalajara/Club America, Chiba/Shimizu S-Pulse, and 8 WTA matches.

## Deliberately NOT done

- **`" 1st Set"` is skipped, not matched.** The analysis suggested adding it to
  `_ALT_SUFFIXES`. That would be wrong: stripping the suffix makes a set-level
  spread/total emit under the *match-level* market key, so a 1st-set line would
  be devigged and compared against full-match prices. Set-level markets need
  their own market keys (a real feature) before those lines can be ingested.
- **No new Odds API league keys.** Adding Argentine Primera / Saudi / UAE /
  K-League to `sports.py` would close ~94 orphans, but it is metered spend and
  that is the user's call. They are now bucketed as `team_coverage` instead.
- **The 44 remaining orphans** are one-sided coverage gaps: the opponent
  (C Liu, V Valdmannova, T Kostovic) or the fixture (St. Louis City/Colorado
  Rapids, Orlando City/Columbus Crew) is absent from the Odds API slate.
