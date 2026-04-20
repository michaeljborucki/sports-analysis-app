# coral33 Integration — End-of-Day Status (2026-04-19)

**This file is the resume-point.** Read it first to pick up where we left off.

**Related:** design doc at `docs/superpowers/specs/2026-04-19-coral33-integration-design.md` (mapping strategy, market shape decoding, cadence rationale).

---

## ▶️ Resume tomorrow — exact next steps

1. **Unblock auth.** In Chrome DevTools while logged into coral33.com, right-click any successful `/cloud/api/Lines/Get_LeagueLines2` request in Network tab → **Copy → Copy as cURL**. Paste into chat. From that I can identify the missing credential (cookie, header, or header-less scheme) and patch `server/odds/books/coral33/client.py` in minutes.

2. **Send the remaining fixtures** (save each as raw JSON response body):
   - NBA: Full day of responses (already have Game / 1st–4th Quarter / Halves / ALT+LINE / NBAPLAYERPRO)
   - NHL: Game, periods, alternates, **player props** (schema not yet confirmed)
   - MLB: Game, 1st 5 Innings, ALT+LINE, MLBPLAYERPRO
   - Tennis: `Get_SportsLeagues` output (so we can enumerate ATP/WTA/CHALLENGER/etc. subtypes) + one `Get_LeagueLines2` per tour
   - NCAA baseball: Game + confirm `sportSubType` string (probe shows if `NCAABASEBALL` is correct)

3. **Probe script, once auth works:** I'll run `client.get_sports_leagues()` and dump the full league list — confirms our sport subtype guesses and captures anything unexpected.

4. **Add player-prop normalizer** once props fixtures are in — second normalizer path keyed on `Team1ID=<player>`, `Team2ID=<stat>`, emits `player_points` / `player_rebounds` / etc. ~1 hour of work once we have sample responses for all 4 sports.

5. **Flip `CORAL33_ENABLED=true` in `.env`** and start the backend — rows should start appearing under `bookmaker_key="coral33"` in the existing odds grid, arbitrage, free-bets, and low-hold tabs.

---

## ✅ Built today

All modules wired, tests green, app boots cleanly. 22 new tests added, 53 total pass.

### Files

- `server/odds/books/coral33/client.py` — `Coral33Client`: auth flow, token-aware `post_form`, retry-on-401 helpers. Uses `curl_cffi` TLS impersonation (Chrome).
- `server/odds/books/coral33/event_matcher.py` — `Coral33EventMatcher`: team-name normalization (lowercase, punctuation strip, alias lookup), ±10 min commence-time window, home/away orientation-agnostic, picks closest time when multiple candidates match.
- `server/odds/books/coral33/mapping.py` — `Coral33Config`, `load_coral33_config()`, `PERIOD_SUFFIX` table.
- `server/odds/books/coral33/normalizer.py` — `normalize_league_lines()`: decodes one `Get_LeagueLines2` response into cache rows. Handles main + period + alt variants. Strips " Alt Line"/" Series" suffixes from team names before event matching. Drops circled games (`Status != 'O'`) and orphan events. Emits `alternate_*` market keys for alt calls.
- `server/odds/books/coral33/fetcher.py` — `Coral33Fetcher`: per-sport APScheduler jobs (main@60s, alt@90s). Captcha-aware back-off to 300s. Separate lifecycle from Odds API fetcher.
- `server/config/coral33.toml` — per-sport endpoint declarations (NBA, NHL, MLB, tennis, NCAA baseball) + empty alias tables ready to populate.
- `server/main.py` — Coral33Fetcher owned by app, started iff `CORAL33_ENABLED=true` + credentials present.
- `server/config.py` + `.env` — 3 new vars: `CORAL33_CUSTOMER_ID`, `CORAL33_PASSWORD`, `CORAL33_ENABLED`.
- `server/odds/commissions.py` — `coral33: 0%`.
- `web/lib/books.ts` — coral33 registered with brand styling (`#BE1622` red).
- `server/tests/test_coral33_normalizer.py` — 9 tests against real HAR fixtures.
- `server/tests/test_coral33_event_matcher.py` — 9 tests.
- `server/tests/test_coral33_mapping.py` — 4 tests.
- `server/tests/fixtures/coral33/*.json` — 20 HAR-captured response fixtures.

### Verified via fixtures (tests pass against real captured data)

- NBA Game / 1st Half / 2nd Half / 1st–4th Quarter responses decode into correct `h2h`, `spreads`, `totals`, `team_totals` rows with correct market-key suffixes.
- NHL Game / 1st–3rd Period responses decode into `h2h_p1` / `spreads_p1` etc.
- `NBA+ALT+LINE` and `HOCKEY+ALTER` responses decode into `alternate_spreads` / `alternate_totals` with " Alt Line" team-name stripping intact.
- Circled games skipped.
- Orphan events (no matching Odds API event) dropped without polluting cache.
- Favorite-team spread sign convention handled.

## 🚧 Blocked: auth

`/cloud/api/System/authenticateCustomer` works — returns a JWT. Every *other* endpoint returns `openresty 401`, even with:

- Correct form body matching HAR exactly
- Chrome TLS fingerprint via `curl_cffi`
- Persistent session, all browser headers, Cloudflare `__cf_bm` cookie, full warmup sequence (`/`, `/sports.html`, auth, Log/write, getAccountInfo)
- JWT in body AND/OR absent (tried both)

Neither HAR nor response inspection reveals the missing credential. The real browser has access established before HAR recording began — whatever was set during login (local storage, HttpOnly cookie from a prior `/login.html` redirect, injected header) is invisible to us.

### What unblocks

**One `Copy as cURL` of a successful `Get_LeagueLines2` request from Chrome DevTools.** That includes every cookie, every header, no HAR scrubbing. From that I can identify the auth mechanism and patch the client in 5 minutes.

## 🗂️ Deferred (waiting on tomorrow's sample data)

- Player props normalizer (`NBAPLAYERPRO`, `MLBPLAYERPRO` — fixture captured but schema confirmed as different: `Team1ID=<player>`, `Team2ID=<stat>`, total-only). Once we have NHL/MLB prop fixtures too, ~1h to add a second normalizer path.
- Tennis `subtypes_main` — need `Get_SportsLeagues` output to enumerate ATP/WTA/tour keys.
- NCAA baseball subtype confirmation — `NCAABASEBALL` is an educated guess.
- Alt totals for basketball (2 per game per user) — confirmed in fixture, already handled.

## Scaffolding that will work the moment auth does

```
start backend → CORAL33_ENABLED=true → Coral33Fetcher.start_all()
  → per sport, APScheduler fires main tier every 60s
  → client.get_league_lines(sport_type, subtype, period) × N
  → normalizer decodes response → event_matcher joins to Odds API event_id
  → cache.upsert() writes rows keyed `coral33`
  → existing /api/odds, /api/arbitrage, /api/free-bets endpoints pick them up
  → UI shows coral33 in book filter, alongside DK/FD/etc.
```

No other surface area changes needed — coral33 is just a new `bookmaker_key` in the existing pipeline.

## Revert

Everything additive. To roll back: `git rm -r server/odds/books/coral33 server/config/coral33.toml server/tests/test_coral33_*.py server/tests/fixtures/coral33`, remove the 3 `.env` vars, remove the import and 10-line block in `main.py`, remove `coral33` from `commissions.py` and `web/lib/books.ts`.
