# Esports Pipeline — Autonomous Decision Log

Decisions made autonomously during design. Sorted by controversy level (highest first).
Review these carefully — they represent judgment calls where reasonable people could disagree.

---

## DECISION 1: Odds Provider — Dual-Provider Architecture (HIGH controversy)

**Decision**: Use **OddsPapi** as the primary odds provider for esports, NOT The Odds API.

**Why**: Live API testing confirmed The Odds API has near-zero esports support:
- `esports_lol` is the only recognized key, but returned **zero events** when queried
- `esports_csgo` returns "Unknown sport" — CS2 is not supported at all
- No other esports keys exist (`esports_dota2`, `esports_valorant`, etc. all fail)
- The Odds API's esports page returns 404

OddsPapi offers: 350+ bookmakers including Pinnacle (the sharpest esports book), sport IDs for CS2 (17), LoL (18), Dota 2 (16), Valorant (61), free tier with 250 req/month.

**Trade-off**: Adds a new API dependency. OddsPapi is a smaller company than The Odds API. But there's literally no alternative — The Odds API cannot provide the data we need.

**What I chose NOT to do**: Scrape Pinnacle directly (fragile, ToS risk), or use OpticOdds (enterprise pricing, overkill for MVP).

**Fallback**: Keep The Odds API code path for `esports_lol` as backup, in case they improve coverage.

---

## DECISION 2: No Elo Rating System for MVP (HIGH controversy)

**Decision**: Do NOT build a dedicated Elo/Glicko rating system for the initial implementation.

**Why**: The system's unique edge is LLM-based reasoning — reading patch notes, analyzing narratives, understanding meta shifts. Traditional quant models (Elo, logistic regression) are well-trodden ground that every sharp bettor already uses. The LLM ensemble IS our model.

Instead, we include HLTV rankings, win rates, and recent form in the briefing text. The LLMs effectively build their own internal Elo when they read "Team A is ranked #3, 70% win rate in 3 months, beat #5 and #8 recently."

**Counter-argument**: Pure quant people will say you need a baseline Elo to anchor predictions. Research shows modified Elo with K=40 and margin-of-victory is the backbone of most esports models. The LCSLarry model uses Elo + features and reportedly achieves 56% ROI.

**My reasoning**: Adding Elo is a Phase 2 enhancement, not an MVP blocker. The ensemble can operate on qualitative data from the briefing. If predictions underperform, Elo ratings can be added as an additional briefing section without architectural changes.

---

## DECISION 3: PandaScore Excluded Due to Betting ToS (MEDIUM controversy)

**Decision**: Do NOT use PandaScore for match data, despite it being the most convenient API.

**Why**: PandaScore's stats plans **explicitly prohibit betting-related usage**. Their betting products require enterprise pricing ($2,000+/month). Using their free/stats tier for a betting pipeline would violate their Terms of Service.

**Instead**: Use HLTV (via `hltv-async-api` Python package) for CS2 data, Oracle's Elixir (free CSV downloads) for LoL data, and Liquipedia API for supplementary roster/tournament data.

**Trade-off**: More fragile data pipeline (community wrappers vs official API), but legally clean. HLTV's unofficial API may break if they change their site.

**Fallback**: If HLTV scraping breaks, Liquipedia API ($49/mo basic) covers both games.

---

## DECISION 4: CS2 First Despite Weaker Odds API Support (MEDIUM controversy)

**Decision**: Follow the prompt's instruction to **start with CS2 first**, even though The Odds API only recognizes LoL.

**Why**: With OddsPapi as the primary odds provider, both games have equal odds coverage. CS2 has richer community data (HLTV is more mature than Oracle's Elixir for betting purposes), and map pool analysis creates a unique edge that LLMs can exploit well.

**Counter-argument**: LoL has richer free statistical data (Oracle's Elixir CSVs with GD@15, vision scores, etc.) and arguably more liquid betting markets globally.

**My reasoning**: The prompt was written with domain expertise — CS2 map veto analysis is specifically called out as the highest-value LLM application in esports betting. The map pool analyst role in the system prompt is the strongest differentiator.

---

## DECISION 5: Game Module Architecture — Subdirectory Pattern (MEDIUM controversy)

**Decision**: Organize game-specific code in a `games/` directory with `games/cs2/` and `games/lol/` subdirectories, each containing their own scrapers, briefing, system prompt, and config.

**Why**: The alternative is putting everything in the existing flat structure with `_cs2` / `_lol` suffixes. The subdirectory pattern is cleaner for a multi-game system and makes it trivial to add new games later (Valorant, Dota 2).

**Trade-off**: Departs from the current flat structure. Existing ensemble/ and agents/ directories stay flat (they're game-agnostic). Only the game-specific layers go into subdirectories.

**Structure**:
```
games/
  cs2/
    scrapers.py      # HLTV team data, schedule, news
    briefing.py      # CS2 briefing template
    config.py        # CS2-specific thresholds, bet slots
    prompt.py        # CS2 expert panel system prompt
  lol/
    scrapers.py      # Oracle's Elixir data, Riot API
    briefing.py      # LoL briefing template
    config.py        # LoL-specific thresholds, bet slots
    prompt.py        # LoL expert panel system prompt
```

---

## DECISION 6: OddsPapi Free Tier Is Sufficient for MVP (LOW-MEDIUM controversy)

**Decision**: Start with OddsPapi's free tier (250 requests/month via REST API).

**Why**: At ~5-10 matches per day for Tier 1/2 events across CS2 and LoL, and 1 odds request per match, we'd use ~150-300 requests/month. The free tier is tight but workable for development and initial operation.

**Trade-off**: May hit rate limits during heavy tournament weeks. No WebSocket real-time data on free tier.

**Upgrade path**: $49/mo Pro tier adds WebSocket streaming and higher limits. Worth it once the system proves profitable.

---

## DECISION 7: Format-Aware Edge Thresholds (LOW controversy)

**Decision**: Implement higher edge thresholds for Bo1 matches (+2% above standard).

**Why**: Bo1 is inherently high-variance — upsets happen more frequently, and even a correctly-identified edge can lose due to single-map variance. The prompt specifically calls this out.

**Thresholds**:
| Format | Moneyline | Map Handicap | Total Maps |
|--------|-----------|-------------|------------|
| Bo3    | 5%        | 6%          | 5%         |
| Bo1    | 7%        | N/A         | N/A        |
| Bo5    | 4%        | 5%          | 4%         |

Bo5 gets LOWER thresholds because more maps = lower variance = more confidence in edge.

---

## DECISION 8: Keep Existing Model Panel, No Esports-Specific Model Tuning (LOW controversy)

**Decision**: Use the same 6 models (Kimi, Claude, GPT-4o, Gemini, DeepSeek, Maverick) for esports without changes.

**Why**: All 6 models have been trained on esports data. There's no evidence any specific model is better at esports prediction. The ensemble's strength is diversity, not individual model expertise.

**What we might revisit**: If certain models consistently underperform on esports (measured by Brier scores), the self-optimizer will naturally down-weight them.

---

## DECISION 9: Match-Fixing Pre-Screen — Tier Filter + Line Movement Alert (LOW controversy)

**Decision**: Only analyze Tier 1 and Tier 2 events. Flag (but don't auto-skip) matches with line movement > 2 standard deviations from expected.

**Why**: Lower-tier esports matches have documented match-fixing issues. Betting on Tier 3+ events is a losing proposition due to information asymmetry, thin markets, and integrity risks.

**What "Tier" means**: Based on tournament prize pool and prestige:
- Tier 1: Majors, Worlds, MSI, IEM Katowice ($500K+ prize pools)
- Tier 2: Regional leagues (LCK, LPL, LEC), RMR events ($50K-500K)
- Tier 3+: Open qualifiers, small online cups — EXCLUDED

---

## DECISION 10: Complete MLB Removal — No Backward Compatibility (LOW controversy)

**Decision**: Delete all MLB code, config, scrapers, and tests entirely. No backward compatibility layer.

**Why**: User explicitly requested "remove any functionality for MLB." The esports pipeline is a clean transformation, not a multi-sport platform. Keeping MLB dead code adds confusion.

**What gets deleted**: `scrapers/pitchers.py`, `scrapers/scores.py`, `scrapers/team_stats.py`, `scrapers/lineups.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`, all MLB config (TEAM_ABBREVS, PARK_FACTORS, PARK_COORDS, TEAM_NAME_TO_ABBREV), MLB-specific briefing template, MLB-specific system prompt, MLB-specific tests, and existing MLB bet data in `data/`.

**Git preserves history**: All MLB code is recoverable via `git log` if ever needed again.
