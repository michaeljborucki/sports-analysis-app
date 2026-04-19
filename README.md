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
