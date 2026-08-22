# Soccer League Grouping and Alternate Spreads Design

## Goal

Make the soccer odds page easier to scan by grouping matches into collapsible league sections, and add Odds API alternate-spread coverage for near-term matches across all five configured regions.

## Scope

This change covers:

- Odds API `alternate_spreads` retrieval for soccer.
- Preservation of soccer league identity from ingestion through the API.
- Collapsible league sections on the soccer odds page.
- Existing alternate-line expansion support for soccer spreads.

It does not add alternate totals, soccer player props, new leagues, or separate league routes.

## Alternate-spread retrieval

Add an enabled `[alternates]` tier to `markets.soccer.toml` with:

- Market: `alternate_spreads`.
- Regions: `us`, `us2`, `us_ex`, `uk`, and `eu`.
- Refresh interval: 300 seconds.
- Upcoming-event window: 12 hours.

The Odds API serves additional markets one event at a time, so the existing per-event fetch path will be used. The fetcher must honor `games_window_hours` for every per-event tier, not only player props. This prevents the soccer alternates tier from querying every match in the general 36-hour display window.

The main soccer tier remains unchanged and continues requesting `h2h`, `spreads`, and `totals` using the league-level endpoint.

## League metadata

The Odds API response already identifies the source competition with its canonical `sport_key` and human-readable `sport_title`. Normalization currently replaces that key with the app-level `soccer` key. Preserve both concepts:

- `sport_key`: the app-level key, still `soccer`.
- `league_key`: the Odds API competition key, such as `soccer_epl`.
- `league_title`: the Odds API competition title, such as `EPL`.

Add nullable `league_key` and `league_title` columns to `odds_snapshot`. Startup migration must add both columns safely to existing databases. Cache upserts, current-row reads, and row-to-game aggregation must carry these values without changing the existing primary key.

Add nullable `league_key` and `league_title` fields to the `Game` API model and matching frontend type. When a game has rows from multiple sources, use the first non-empty league value. Odds API rows provide the authoritative league metadata.

Coral33-only soccer events without Odds API metadata remain valid and receive no fabricated league. The UI groups them under `Other Soccer`.

## Soccer page presentation

League grouping applies only when `sport.key === "soccer"`; other sports retain the current flat table.

The soccer page renders one collapsible section per league:

- Header shows the league title and visible match count.
- Sections are expanded by default.
- Live leagues sort first.
- Remaining leagues sort by their earliest visible kickoff.
- Matches within a league remain ordered by kickoff.
- Events without league metadata appear in a final `Other Soccer` section.

The existing global All/Pre/Live filter is applied before grouping. Empty leagues therefore disappear automatically. Market tabs remain global across the page so switching from Moneyline to Spread or Total updates every league section consistently.

## Alternate-line UI

Set soccer's Spread market group `altKey` to `alternate_spreads`. The existing alternate-lines expansion sheet remains the only detailed alternate-line view; the main grid continues to display featured `spreads` lines.

If an event has no alternate spreads, the main spread row continues to work and the expansion affordance remains absent for that event.

## Failure behavior

- A failed alternate-spread request must not remove or block main soccer markets.
- Empty or unsupported alternate responses are treated as no coverage and do not create placeholder rows.
- Missing league metadata falls back to `Other Soccer` without failing API validation.
- Existing cache databases migrate in place without deleting odds history.

## Testing

Add focused tests that prove:

1. Soccer config enables `alternate_spreads` for all five regions with a 12-hour window.
2. The per-event fetcher respects `games_window_hours` for alternates.
3. Odds API normalization preserves `league_key` and `league_title` while retaining app-level `sport_key="soccer"`.
4. Cache migration, upsert, read, and game aggregation retain league metadata.
5. API serialization includes nullable league fields.
6. Frontend grouping orders live leagues first, then earliest kickoff, and places missing metadata in `Other Soccer`.
7. Soccer Spread is connected to `alternate_spreads` while other sports remain unchanged.

Run the relevant backend test modules, frontend unit tests, targeted linting, TypeScript checks, and `git diff --check`. Any unrelated pre-existing type or lint failures will be reported separately.

## Operational impact

The alternates tier can issue one Odds API request per soccer event inside the next 12 hours every five minutes. Each request asks for all five regions. Empty responses do not consume market credits under the provider's documented quota rules, but broad regional coverage is intentionally accepted here in exchange for better line-shopping coverage.

After deployment, restart or hot-reload the fetcher so the new tier is scheduled, then force one refresh and verify `alternate_spreads` rows and league metadata in `/api/odds/soccer`.
