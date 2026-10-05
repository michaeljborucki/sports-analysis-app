# betting-site — sports-betting edge finder

Monorepo (`github.com/michaeljborucki/sports-analysis-app`, branch `main`):
`server/` (FastAPI + APScheduler + SQLite, Python 3.11, uvicorn :8000), `web/`
(Next.js 16 / React 19 / SWR + SSE / Tailwind 4, :3000), `agents/` (per-sport
MiroFish pipelines), `scripts/`, `docs/superpowers/` (specs/plans).

`ROADMAP.md` is the work index — "number 8", "tier 2", "13a" refer to its items;
the user gates items individually (never assume the whole tier is approved), and
leftover items get written back to markdown. **`README.md` is badly stale** (still
describes the two-page MLB MVP) — trust the code, not the README.

## Money gates (never flip these yourself)

- `cache_mode=live` IS the user's approval to spend Odds API budget. Never auto-flip
  it to live.

## Domain rules

- Kalshi/Polymarket: always surface the **ASK** (what it costs to buy), never the
  bid. Fees: Kalshi ~7% on market orders only; Polymarket 5%. Freshness target
  ~1 minute — stale odds are treated as bugs.
- Kelly values from `/api/ev` are **percentages** (4.6 means 4.6%), not fractions.
- Coral33 (voice-transcribed as "Quarrel33"/"Coral 33"): scraped via `curl_cffi`
  Chrome impersonation through Decodo residential proxies (ports 10001–10007),
  per-account JWTs.
- Never silently drop market types — the user notices and audits (first-5 totals/
  moneylines). Player props are included in EV, arbitrage, and low-hold scanners. `wager_type`
  (straight/parlay/both) is Coral33-only, NULL for other books.

## Run / verify

```bash
source .venv/bin/activate && uvicorn server.main:app --host 127.0.0.1 --port 8000
cd web && npm run dev            # :3000
lsof -ti:8000,3000 | xargs kill  # stop both
```

- Launch locally and verify in the browser/logs before designing further or
  claiming done — the user re-checks with screenshots. A page-load performance
  regression halts all other work until fixed.
- Tests: `pytest server/tests`; web: `npx tsc --noEmit` / `npm run build`.
- **Known pre-existing failures — do not chase as regressions:**
  `server/tests/test_ev.py::test_three_way_markets_are_skipped`, and ~5 tsc errors
  confined to `web/app/bets/` (CLVChart.tsx, page.tsx).
- After changing server models, regenerate types:
  `cd web && npx openapi-typescript ./openapi.json -o ./types/api.ts`
  (`web/openapi.json` drifts — regenerate it too).
- Use `python3` (pyenv), never `python`.

## Secrets

Push everything to the monorepo EXCEPT: `.env` (account passwords + proxy
credentials), HAR fixtures (contain JWTs), and keys. Repo size doesn't matter;
leaks do.

For `web/` specifics see `web/AGENTS.md`: this Next.js version differs from
training data — read `node_modules/next/dist/docs/` before writing web code.
