# Empty-state copy library

Structured copy for the teaching `<EmptyState>` primitive (`web/components/empty-state.tsx`). Covers the surfaces the next agent (building `/edges` and adjacent scanner / sport / dashboard / settings pages) will render when data is legitimately absent.

Power-user voice: diagnose the mechanical cause, not soothe. Name real state variables where they exist (`staleSeconds`, `minEv`, `visibleBooks`, `liveFilter`, `disabled_markets`, `last_fetch_at`). Assume the reader is the developer-bettor running the site locally.

Templated values use `{braces}`. If a value is unavailable at render, drop the sentence rather than print a placeholder.

---

## 1. `/edges` — no opportunities (all modes selected)

**Tone:** `warning` when cache is stale, else `neutral`.

**Title:** No edges right now — and that might be correct

**Body:** Scanner last ran against a cache {age} old ({scanned_at}). If no book is currently mispriced vs. the sharp consensus, the result is legitimately empty — this isn't necessarily a bug.

**Hints:**
- **Cache age** — scanner drops offered prices older than `{stale_seconds}`s; if the fetcher is off or behind, the scanner runs on a frozen snapshot and will find nothing new.
- **Missing anchors** — +EV needs Pinnacle (or a sharp consensus); Arb needs two books on opposite sides of the same line. If all sharp books are hidden in Settings, the anchors don't fire.
- **Mode overlap** — "All modes" still respects each mode's own thresholds (`minEv`, `minArbPct`, `minHold`). A tight default can leave all four empty at once.

**Action:** "Refresh now" → `mutate()` on the scanner SWR key. Secondary "Open Settings" ghost button if `visibleBooks` excludes Pinnacle.

---

## 2. `/edges` — no opportunities (Arb mode)

**Title:** No arbitrage pairs in the current cache

**Body:** Arbitrage requires two visible books offering opposite sides of the same market with implied probabilities summing under 100%. Right now that combination doesn't exist across your visible set.

**Hints:**
- **Two-book minimum** — your visible set has `{visibleCount}` book{visibleCount !== 1 ? "s" : ""}; arbs need at least two that both post the same market.
- **Line matching** — arbs also need matching points. Alt-line arbs are more common than mainline arbs but only surface if both sides of a non-main line are cached.
- **Cache staleness** — lines shift; a {age}-old cache will keep showing yesterday's closed arbs or, more often, none.

**Action:** "Refresh now" → `mutate()`. If `visibleBooks.size < 2`, swap the primary CTA for "Enable more books in Settings".

---

## 3. `/edges` — no opportunities (+EV mode, `min_ev > 0`)

**Title:** No +EV plays above `+{minEv}%`

**Body:** Scanner compared every offered price against the de-vigged sharp consensus; nothing currently clears your `min_ev` floor. Lower the floor or wait for prices to move.

**Hints:**
- **Anchor books** — +EV uses Pinnacle (or Circa / the sharp consensus) as "fair". If Pinnacle is hidden in Settings, the anchor falls back to consensus and the edge signal weakens.
- **Filter overlap** — `min_ev ≥ {minEv}%` + `max_odds ≤ {maxOdds}` can eliminate all rows together even when either alone would pass. Widen one.
- **Cache stale** — scanner drops offered prices older than `{stale_seconds}`s. A stale cache can only surface closed edges; fresh ones come in after a fetcher cycle.

**Action:** Primary "Lower min EV to +1%" (sets the local filter to the smallest non-zero tier). Secondary "Refresh now".

---

## 4. `/edges` — no opportunities (Low Hold mode)

**Title:** No low-hold pairs under `{maxHold}%`

**Body:** Low-hold means two offered prices that, together, produce a book's edge under your threshold — profitable when combined with promo or rakeback. None of the current visible pairs clear the bar.

**Hints:**
- **Two-book minimum** — same mechanic as arbs; low-hold requires opposite sides on different books at matched lines.
- **Threshold tightness** — `{maxHold}%` is a hard ceiling. Most real-world pairs sit at 1.5–3%; sub-1% is rare outside promo windows.
- **Cache age** — prices drift fast at the 2%-hold band; a {age}-old cache shows lagging rather than current pairs.

**Action:** "Raise threshold to 2%" (adjusts the local filter one tier looser). Secondary "Refresh now".

---

## 5. `/edges` — no opportunities (Free Bets mode)

**Title:** No free-bet conversions match your stake

**Body:** Free-bet mode calculates the long-odds leg that maximizes EV when cashing a promo credit. Nothing in the cache currently returns enough $ at the configured stake of `${stake}`.

**Hints:**
- **Odds range** — free-bet EV rises with longer odds; if `max_odds ≤ {maxOdds}`, the long legs are capped out of the profitable zone.
- **Book availability** — the long leg has to exist on a book you actually have a promo balance on. Filter the offered-book dropdown to match your active promos.
- **Cache age** — long-odds props and futures drift less often but stale out the same way; refresh if `{age}` > a few minutes.

**Action:** "Widen max odds to +800". Secondary "Refresh now".

---

## 6. `/edges` — filtered to zero (user applied an extra book filter)

**Title:** Your book filter eliminated all `{modeLabel}` edges

**Body:** The underlying cache has `{rawCount}` opportunit{rawCount === 1 ? "y" : "ies"}, but none pass the offered-book filter `{filterValue}`. Clear the filter to restore the list.

**Hints:**
- **Filter scope** — the offered-book dropdown narrows *which book* the edge is on, not which books are used as anchors.
- **Single-book pinning** — choosing one book hides every edge not currently posted by that book; useful for action planning, not for surveying the market.

**Action:** Primary "Clear book filter" → resets to `All`.

---

## 7. `/odds/{sport}` — no games today for sport

**Title:** No `{sportLabel}` games in the cache today

**Body:** The fetcher hasn't cached any events for `{sportLabel}`. Either the league is off-season / off-day, or the sport is disabled / not in the fetcher rotation.

**Hints:**
- **Schedule** — today is `{today}`; some leagues (NFL in April, NHL mid-summer) simply have no slate.
- **Disabled sport** — if `disabled_sports` includes `{sport}`, the fetcher skips pulling it entirely.
- **Cache age** — if `last_fetch_at` is hours old, a slate that started since may not show yet.

**Action:** Primary "Open Settings" if `disabled_sports.includes(sport)`; otherwise secondary "Refresh now".

---

## 8. `/odds/{sport}` — `Pre` filter hides all games because slate is live

**Title:** All `{sportLabel}` games are in-play — `Pre` filter is hiding them

**Body:** The cache has `{gameCount}` `{sportLabel}` game{gameCount === 1 ? "" : "s"} today, but every one of them has already tipped. The current `liveFilter = "pre"` removes them.

**Hints:**
- **Filter mechanic** — `Pre` keeps games with `commence_time > now`; `Live` keeps the rest; `All` shows both.
- **In-play coverage** — some books pull odds once games start, so live slates may also drop book columns until lines repost.

**Action:** Primary "Switch to All" → `setLiveFilter("all")`. Secondary "Switch to Live" → `setLiveFilter("live")`.

---

## 9. `/picks/{sport}` — no picks from any agent

**Title:** No picks published for `{sportLabel}` today

**Body:** Agents haven't pushed picks for this sport yet, or the pick cache hasn't been populated for today's date. Picks are agent-driven, not live-computed — they arrive on their own schedule.

**Hints:**
- **Agent cadence** — each sport's agent runs on its own schedule (NBA/MLB daily pre-slate; Soccer per-match). If today's cadence hasn't fired, no picks exist.
- **Day boundary** — picks are date-keyed in the agent's local timezone; a timezone mismatch near midnight can hide a published set.
- **Upstream failure** — if the agent errored on grading or fetching, it often skips publishing. Check `picks/` logs.

**Action:** Secondary "Check pipeline health" → links to `/dashboard` fetcher/health section. No primary CTA — empty is usually a genuine waiting state.

---

## 10. `/dashboard` — no data (empty cache, first run)

**Tone:** `warning` (first-run nudge).

**Title:** Cache is empty — start the fetcher to pull prices

**Body:** No `last_fetch_at` timestamp is set. Nothing here will populate until the fetcher has run at least one cycle, which takes 20–60s depending on your sport selection.

**Hints:**
- **Fetcher OFF** — the fetcher toggle in the top right controls Odds API pulls; it's metered, so leaving it on consumes quota.
- **coral33 is free** — coral33 integration is unmetered and can be toggled on without cost. If coral33 is enabled but the fetcher is off, you'll see coral33 data only.
- **First cycle** — even with fetcher on, the first cycle fills mains before props; expect 1–2 minutes to full.

**Action:** Primary "Refresh coral33 now" (no-cost), secondary "Open Settings" to review sport / market selection before enabling the paid fetcher.

---

## 11. `/settings` — no sports configured

**Title:** No sports loaded in the registry

**Body:** The Settings payload returned zero sports. This is a backend state, not a user toggle — the FastAPI server either hasn't seeded its sport registry or can't reach the Odds API catalog.

**Hints:**
- **Backend reachable?** — if the page header says "Backend unreachable", FastAPI is down; nothing here will help until it's back.
- **Registry seed** — sport registry is populated at backend startup from the Odds API catalog. A failed seed leaves the list empty without erroring the endpoint.
- **Config file** — manual sport additions live in the backend config; check `sports.yaml` / equivalent if the registry persistently returns empty.

**Action:** Primary "Reload settings" → `mutate(apiPaths.settings)`. Secondary "Open API health" → `/dashboard` health chip or `/api/health`.

---

## Design notes for the next agent

- **Always compute the state variables before writing title copy.** "No edges — cache is 2m old" is load-bearing. "No edges found" is noise.
- **Hints are optional but high-value on scanner pages**, where 3 distinct causes (cache / filter / anchor) are all plausible at once.
- **One primary action max.** If there are two equally good CTAs, the second one is a ghost button.
- **`tone="warning"`** is reserved for empty states where the most likely cause is a stale cache or an unfinished fetcher cycle — i.e., situations where refreshing will probably fix it. Don't use warning for "no games today, it's the off-season" — that's genuinely neutral.
- **Avoid novice explainers.** The user already knows what +EV / hold / arb are; the empty state is a diagnostic, not a tutorial.
