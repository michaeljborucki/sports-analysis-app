# Betting Site — MLB MVP

Personal odds aggregator + picks viewer. Laptop-only, local-only, no auth.

Two pages:
- **`/odds/mlb`** — live odds from the US sportsbooks, dense Bloomberg-style grid.
- **`/picks/mlb`** — picks from the `baseball-agents` pipeline, ranked by edge, click a row for the reasoning.

## Run

```bash
# Terminal A — backend (FastAPI + APScheduler on :8000)
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000

# Terminal B — frontend (Next.js on :3000)
cd web
npm run dev
```

Open <http://localhost:3000> — redirects to `/odds/mlb`.

## Env

`.env` is created from `.env.example`. Required: `ODDS_API_KEY` (mirror from `agents/baseball-agents/.env`). Optional: `BET_CARD_DIR`, `BETS_CSV`, `ODDS_POLL_INTERVAL`.

## Shared live-odds feed (agent reuse)

The backend already polls The Odds API for every enabled sport and stores the
results in one multi-sport cache (`server/odds/cache.py`). The sibling agent
pipelines under `agents/` can **reuse that same cache** instead of each
spending their own Odds API credits on the same games.

The backend exposes the cache in The Odds API's native JSON shape at:

```
GET /api/odds/{sport}/raw   →   { "data": [ ...events... ], "stale_seconds": N }
```

Each event mirrors a direct `/sports/<key>/odds` response (all markets,
including props; player/team folded back into `description`), so an agent runs
it through the exact same parsers it uses for a direct pull. The feed carries
**every** book in the cache — the Odds API books plus the directly-fetched ones
(coral33, kalshi, polymarket) — so all of them feed the agents' consensus
devig.

To switch an agent over, set in its `.env`:

```bash
ODDS_FEED_BASE_URL=http://127.0.0.1:8000   # the running backend
ODDS_FEED_SPORT=mlb                        # backend app sport key (see server/sports.py)
```

Live odds then come from the shared cache; if the backend is down or doesn't
yet carry that sport, the agent transparently falls back to a direct Odds API
pull. Historical odds (closing-line backfill) always use the Odds API. Adding a
new sport to the shared feed is just registering it in `server/sports.py` +
`server/config/markets.<sport>.toml`, then pointing the agent's
`ODDS_FEED_SPORT` at it.

## Tests

```bash
# Backend
source .venv/bin/activate
pytest server/tests -v

# Frontend typecheck + build
cd web
npx tsc --noEmit
npm run build
```

## Design docs

- Spec: `docs/superpowers/specs/2026-04-18-betting-site-mvp-design.md`
- Plan: `docs/superpowers/plans/2026-04-19-betting-site-mvp-plan.md`
- Visual mockups (for reference): `.superpowers/brainstorm/67342-1776574509/*.html`

## Deferred to v2

- Mobile layout (desktop-only for now)
- Multi-sport (directory is sport-parameterized — add NBA by adding new routes + config)
- Deployment (upgrade backend URL to env var, move picks reader from filesystem to HTTP push)
- Auth (no login needed for local-only)
- WebSocket line streaming (polling works for MVP)
- Per-event market enrichment (team totals, alt lines — not wired in the fetcher)
- Graded-picks history page
- Drag-to-reorder sportsbook columns + saved user preferences
