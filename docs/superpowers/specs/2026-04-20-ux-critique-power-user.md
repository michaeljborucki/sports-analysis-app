# Power-User UX Critique — 2026-04-20

**Reviewer:** sharp bettor, $5K–$20K/day, 40-book spread, lives in Unabated + OddsJam + BettingPros. Muscle memory is fast; I don't read, I scan.

---

## 1. A 5-minute bet-hunting session

It's 12:55 PM. Lakers tip at 4. I open the tool cold.

**00:00** — land on Dashboard. "API QUOTA: 4,569,756 (4570% remaining)" — I laugh, then lose a beat because I don't know if the rest of the numbers on this page lie too. "Top ARBS" shows a +239.77% MLB baseball spread @4.5 — obviously stale data, no freshness chip on the row. **Trust is already a problem.**

**00:20** — click **Arbitrage**. Good — sortable, ROI descending, dual-book logos, pair of prices, MARKET column. I want to filter to my limit-friendly books (Circa, BetOnline, Pinnacle). "Must include" dropdown — fine, but I want a **blacklist** more than a whitelist ("hide anything with ESPN BET on one side" — they're going to limit me in two weeks). There's no row action. I can't click +239.77% to get a stake-split calculator. I can't copy the line. I can't open either book's bet slip in a new tab. **The page is a viewer, not a workbench.**

**01:30** — **Low Hold**. Same shape as Arb. Same row-action gap. Holds are 0.21% – 0.94%; at those margins I'm not firing without a per-row Kelly/stake-size input. I'd also want to see **the hold trend over the last 10 minutes** — is it tightening or drifting?

**02:20** — **+EV**. "No +EV edges match current filters." Min 2% is on. I drop to ≥1% — still nothing. No hint of *why* (stale cache? fair-price model off? 3-way filter?). A pro scanner always tells you the top-3 near-misses so you trust the pipeline.

**03:00** — **Odds → NBA**. Now it's fast. Best-price tint, consensus col, expand arrow. I expand Blazers@Spurs Spread — **40+ alt rows slam the viewport** and I lose my scroll position. I have to hunt my way back to Rockets@Lakers. Unbearable the second time.

**04:00** — **Props → NBA → Points**. 298 rows of Brandon Ingram alts with mostly em-dashes; I have to scroll to find the 1 row where 7 books priced. The empty matrix cells carry as much visual weight as the real prices. I can't sort by "most-priced row" or "widest spread." I give up and go back to OddsJam.

**05:00** — nothing staked. That's the indictment.

---

## 2. What I'd steal from Unabated / OddsJam

1. **OddsJam's per-row stake calculator.** Click the ROI — a drawer opens with bankroll, Kelly fraction, round-to-$5, and the exact stake per side with profit preview. Copies to clipboard. Right now this app gives me the *edge*; OddsJam gives me *the bet*.
2. **Unabated's "No-Vig Fair" consensus column.** I see `CONSENSUS` with a number but I don't know if it's median, de-vigged, or raw. Unabated labels the method and lets me swap between **sharp consensus** (Pinny + Circa + BetOnline weighted) vs. **market median**. That distinction is everything for a +EV model.
3. **OddsJam's book-click deeplink.** Clicking a price opens the bet slip at that book with the selection pre-filled. Even a middle-click "open book's event page in new tab" would cut 30 seconds per bet. Right now prices aren't even hyperlinks — they're dead text.

---

## 3. Ten gaps for a pro use-case

1. **No per-row stake calculator.** Arb/Low-Hold rows need a `$` input that computes both stakes, net profit, and rounded increments.
2. **No clipboard action.** I can't copy "Team Total O 3.5 @ +100 Pinnacle" to stash in my bet tracker.
3. **No game/market star or pin.** I can't flag Lakers@Rockets as "watch closely" and pin it to the top.
4. **No keyboard shortcuts.** `g a` → Arbitrage, `/` → focus filter, `j/k` to move rows, `c` to copy — Unabated does all of this. This app has zero.
5. **No compact density mode.** Row height is generous; on a 27" I want 2× the rows visible. One `Cmd-Shift-D` toggle.
6. **No portfolio/ledger view.** I fire ~60 bets/day across 15 books. I need a "what have I staked today, what's my exposure per game, what's my CLV" view. Picks tab shows agent recommendations, not my actions.
7. **No blacklist filter on books.** Whitelist ("must include") isn't enough; I need to *exclude* books that ding my accounts (DK, FD when I'm limited).
8. **No stake-limit per book.** I need to annotate "Fanatics max $250 on NBA spreads" and see it inline when Fanatics is a leg.
9. **No price history / line movement sparkline.** Every row in Arb/Low-Hold should have a 10-point sparkline for both legs. Is +239 stale or still there?
10. **No alt-lines drawer-as-sidesheet.** Inline expansion destroys my scroll context (see also the P1 audit). Needs to be a right-docked panel I can leave open while I scan other games.

Bonus gripes: no CSV/JSON export on any scanner; no "near-miss" explainer on empty EV state; no timestamp per opportunity (only page-level freshness); no URL state for filters — I can't bookmark "NBA arbs ≥3% excluding ESPN BET".

---

## 4. The one feature that would make me switch

**A workbench row.** Every row in Arb/Low-Hold/EV expands into an inline workbench: bankroll + Kelly fraction input, computed stakes per leg with round-to-$X, a "Place via bookmarked deeplinks" trio of buttons (one per leg), a sparkline of the edge over the last 15 minutes, and a **"Log to ledger"** button that writes the bet to my portfolio view with timestamp, expected CLV, and expected value.

That single feature turns this from *another odds viewer* into *the place I actually click bets*. Unabated gives me half of it (stake calc) and OddsJam gives me the other half (deeplinks). Neither gives me the ledger. Build all three on top of the already-good arbitrage/low-hold tables you have, and I'd run this as my daily driver.

---

## What's genuinely good

- **Odds grid moneyline view is clean.** Best-price tint + consensus + book logos is a pro layout. Better than OddsJam's cluttered version.
- **Global Live / Pre / All filter in the header is exactly right.** Persists across routes, no fuss.
- **Market tabs on Odds (ML/Spread/Total/Q1/1H) are fast and obvious.** Keep this pattern; extend it to props.
- **Tennis Picks page** — the EDGE/PROB/STAKE columns with the agent attribution chip is the single most pro-feeling view in the whole app. Make the scanner pages look like this.
