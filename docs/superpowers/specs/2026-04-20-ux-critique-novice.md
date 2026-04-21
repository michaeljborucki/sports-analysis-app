# First-Time User UX Critique

*Persona: casual DraftKings bettor, ~10 bets total, no sharp vocabulary. First visit.*

## Session transcript (first 10 minutes)

**0:00 — Landed on Dashboard (`01-dashboard.png`).** OK, dark theme, looks like a Bloomberg terminal. Top says "Dashboard Odds Props Picks Arbitrage Low Hold +EV Free Bets Settings." I know Odds and Props. The rest I don't. "Fetcher OFF" in the top right — is the site broken? There's a giant "4,569,756 API Quota / 4570% remaining" card and I have no idea what that means to me. "Top Arbs" shows "+239.77%" on a Braves game. A 239% return? That can't be real. The picks table has "EDGE 15.0%" and "STAKE 1u". What's a "u"? Is that a unit, like a dollar? "Team Total: under 8.5" — whose total? This bet has a price of +106 with 15% edge, which sounds amazing, so... why isn't everyone just clicking it? Confused but curious.

**1:30 — Clicked Odds (`02-odds-nba.png`).** Loading skeleton for a while. Fine.

**2:00 — Odds loaded (`02c-odds-nba-expanded.png`).** A yellow banner yells "Odds last updated 91m 24s ago — the fetcher may be stuck. Check /api/health." I am not going to check /api/health, I'm a person. Tabs: "MONEYLINE SPREAD TOTAL 1H ML 1H SPREAD 1H TOTAL Q1 ML Q1 SPREAD Q1 TOTAL." I know moneyline. The first column after teams is "BEST" with a little book logo. Then "CONSENSUS." Then like 12 sportsbook columns with tiny logos I mostly don't recognize. Numbers are green and red. The Raptors are +425 at one book and +315 at another — same team, same game. Why are they different? Is one a typo? I realize maybe I'm supposed to pick the best number, but nothing tells me that.

**3:30 — Clicked Props (`03-props-nba.png`).** Another loading skeleton. Waited. It stayed empty. I assume props are broken. Moved on.

**4:00 — Clicked Arbitrage (`05b-arbitrage-loaded.png`).** Tiny tiny text. First column is a percentage in green (+1.08%, +1.03%...). "MARKET" says "Spread +5.5," "SIDE A" / "SIDE B." I think I see: bet both sides and win 1%? Is that legal? Is that gambling? Why is this allowed? Also every row looks identical, there are fifty of them, I can't tell which one is "best" or how much money I'd need. Nothing tells me how to actually place these bets or whether I need accounts on both books.

**5:30 — Clicked Low Hold.** Looks exactly like Arbitrage but the percentages are different (negative? 0.7%? 0.5%?) and they have minus signs. Wait, a green negative number? Is that good or bad? No explanation.

**6:30 — Clicked +EV (`07b-ev-loaded.png`).** "offered price vs sharp fair · sorted EV desc · displayed EV is theoretical." I understood three of those words. Empty state: "No +EV edges match current filters — try lowering min EV or widening max odds." Filters: ALL ≥1% ≥2% ≥3% ≥5% / ALL ≤+300 ≤+500 ≤+800 / ALL PIN CON / OFFERED BOOK All / STAKE $1000. PIN and CON? I clicked ALL on everything. Still empty. Gave up.

**7:30 — Clicked Free Bets (`08b-free-bets-loaded.png`).** Thought this meant "sportsbook promos, free $20 bets." Instead it's another giant table that looks like arbitrage with an "EXPECTED VALUE" column in dollars. Nothing on the page explains that this is for converting a promo credit into cash. I don't have any promos loaded and I wasn't asked. Confused.

**8:30 — Clicked Picks.** I remember seeing "Picks by Edge" on the dashboard. Is this the list of bets the robot thinks I should make? That's the only page I'd actually use, but I'm not sure if clicking the row places the bet, copies it, or does nothing. I'm scared to click.

**9:00 — Clicked Settings (`09-settings.png`).** A wall of 60 sportsbook checkboxes. "10 / 60 enabled." Why are only 10 on? Am I supposed to know which to pick? Tiers: "4 tiers · 68 markets." What's a tier? Below: "MLB Tennis NBA NHL NCAA Baseball." No NFL? It's April, fine, but no warning. Closed the tab mentally here.

## Top 10 things that made no sense

1. **"Fetcher OFF"** — reads like the site is broken. I don't know I'm supposed to turn it on, or that it costs money to leave on.
2. **"+239.77% arb"** — a 240% return label without context screams "too good to be true / scam."
3. **"1u" / "0.5u" stakes** — unit sizing is a sharp concept; I need "bet $50" or "bet 1% of bankroll."
4. **"EDGE 15.0%"** — edge vs. what? My bookie? Vegas? Truth?
5. **"Consensus" column** — consensus of whom? Why is it different from "Best"?
6. **"Low Hold" with negative green numbers** — green usually means good; minus signs confuse.
7. **"+EV" entire page** — the acronym is never expanded. "offered price vs sharp fair" might as well be Latin.
8. **"PIN / CON" filter buttons** — Pinnacle/Consensus, obviously, to someone who knows; to me: random letters.
9. **"Free Bets" label** — I expected promo offers, got a promo-conversion calculator with no explanation.
10. **"API Quota 4,569,756 / 4570% remaining"** — a developer metric on the user-facing dashboard. Feels like I snuck into the back office.

Honorable mentions: 60-book checkbox wall with zero guidance, "4 tiers" with no definition, yellow "fetcher may be stuck / check /api/health" error speaking to engineers not users, tiny book logos I can't identify.

## What would have kept me in the app

- **A 30-second welcome modal on first load**: "This site compares odds across sportsbooks to find you better prices than DraftKings. Here's what each tab does."
- **Inline one-line definitions under every page title**: "Arbitrage = bet both sides across two books for a guaranteed small profit. You need accounts at both."
- **Hover tooltips on every jargon word** — EV, hold, edge, consensus, Pinnacle, de-vig, unit, tier, fair price. First encounter = dotted underline + tooltip.
- **A "Lite mode" / "Beginner mode" toggle** that hides +EV, Low Hold, Arbitrage, Free Bets and just shows: "Today's Games → Best Price Across Books → Top Picks." Promote the sharp tabs once the user opts in.
- **Translate "stake" to dollars** by default (tie to a bankroll the user enters), not units.
- **Kill developer-facing copy** on the user surface: API quota, /api/health links, "fetcher" naming. Rename "Fetcher" to "Live updates" with a simple ON/OFF and a cost warning only in Settings.
- **Empty states that teach**, not just filter advice. The +EV empty state should explain what +EV is before telling me to loosen filters.
- **An onboarding checklist** in Settings: "1) Pick the books you have accounts at. 2) Set your bankroll. 3) Pick your sports." Right now I'm just staring at 60 checkboxes.
- **A "How do I actually place this bet?" link** on every arb / EV row — a mini walkthrough: open book, find market, enter stake, confirm.
- **Color key legend** somewhere visible — what does green mean, red mean, yellow row highlight mean.

## One-sentence guesses for each page

- **Dashboard** — "Today's important stuff and some scoreboard-looking numbers I don't understand."
- **Odds** — "A giant spreadsheet comparing prices at a bunch of sportsbooks I've never heard of."
- **Props** — "Broken — it never loaded for me."
- **Picks** — "A robot tells me which bets to make, I think, but I'm not sure if I'm supposed to trust it."
- **Arbitrage** — "Some trick where you bet both sides and always win a tiny amount? Seems illegal."
- **Low Hold** — "Like Arbitrage but with smaller, negative-looking numbers, no idea."
- **+EV** — "A page full of filter buttons and a message telling me nothing matched."
- **Free Bets** — "I thought promos; it's actually more tables that look like arbitrage."
- **Settings** — "Turn sportsbooks on and off, but I don't know which ones I'm supposed to turn on."
