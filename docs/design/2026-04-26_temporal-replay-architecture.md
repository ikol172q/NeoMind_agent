# Temporal replay architecture — `as_of` time control + re-run preservation

**Date**: 2026-04-26
**Status**: Phase 1 + Phase 2 (schema) shipped; Phase 3-4 designed, not built.

## TL;DR

- Today both Research and Strategies tabs are pinned to "now" — there's no way to ask "what did the agent see on Tuesday?" with both tabs in sync.
- Snapshots already exist in `<root>/<project_id>/lattice_snapshots/YYYY-MM-DD.json` but they cover Research only and re-running today **overwrites** the file.
- This doc commits to a 4-phase plan. Phase 1 ships an `as_of` switcher that snaps both tabs to one date. Phase 2 makes re-runs of the same day non-destructive so the operator can replay any specific run later. Phase 3-4 lay out range mode + bitemporal market-data versioning, written down so we don't paint ourselves into a corner now.

## Driving questions

1. **Coherence**: when I look at the lattice for date X, the "today_fit" scores on the Strategies tab better also be against date X — not against now.
2. **Replay**: I should be able to re-run the lattice and still get to the **previous** run's output later (same day, different runs). Otherwise re-runs destroy evidence.
3. **Range**: I should be able to ask "what did the agent surface in the last 7 days?" and get an aggregate, not just one snapshot at a time.
4. **Bitemporal honesty**: a stored snapshot was computed using whatever data was available at recording time. If I refetch market data for that day later, I should be able to tell which version of the input data fed the snapshot.

## Phase 1 — single-day `as_of` switcher (shipping)

**Scope.** A global `as_of` value, threaded through every lattice-derived API call. `LIVE` (the default) means "compute from current data right now"; a specific date means "read the stored snapshot".

**State.** `appAsOf: 'live' | YYYY-MM-DD` lifted to `App.tsx`. Top-bar picker reads `useLatticeSnapshots()` to populate available dates. Default sticks at LIVE.

**Backend changes.** Each of these endpoints picks up an optional `as_of` query parameter:

- `/api/strategies/lattice-fit?as_of=...`
- `/api/strategies/by-theme?as_of=...`
- `/api/strategies/{id}/themes-as-of?as_of=...` (renamed from `themes-today` for honesty)
- `/api/strategies/time-aware?as_of=...` (passthrough — calendars don't change with `as_of`, but future events DO; need this for "5 days ago, FOMC was 9d out, not 4d out")

When `as_of` is set, the handler reads `read_snapshot(project_id, as_of)` and pulls themes from `payload.themes`. When not set, it calls `build_themes(project_id)` live.

A historical snapshot that's missing returns 404 with a body the UI can render as "no snapshot for that date — pick another or backfill".

**Cross-tab jump preserves time.** Both `jumpToResearch` and `jumpToStrategies` carry `as_of`. The destination tab's URL/state already has it.

## Phase 2 — re-run preservation (shipping schema, not yet wired)

**Problem.** Today's snapshot path is `<root>/<project_id>/lattice_snapshots/2026-04-26.json`. Running the lattice twice on the same day overwrites the first run's evidence — exactly what we don't want for an audit-first system.

**Migration.** One level deeper:

```
<root>/<project_id>/lattice_snapshots/2026-04-26/<run_id>.json   ← Phase 2
<root>/<project_id>/lattice_snapshots/2026-04-26.json            ← Phase 1 (legacy)
```

Each `run_id` is a UUID matching the corresponding `analysis_runs.run_id` row, so a snapshot is fully cross-referenceable to its scheduler/manual run record (job_name, started_at, error_message, rows_written, the SQLite drill-down we already built). Old single-file layout is auto-detected on read and treated as a single legacy run.

**API additions.**

- `/api/lattice/snapshots?project_id=...` — already lists dates; extend each entry with `run_count: int`. Each entry also keeps `latest_run_id` for the default lookup.
- `/api/lattice/snapshot?project_id=...&date=...&run_id=...` — when `run_id` omitted, returns the latest run for that date (matches Phase 1 behaviour). When set, returns that exact run.
- `/api/lattice/runs-for-date?project_id=...&date=...` — list every run for a given date, newest first, including its `run_id`, `recorded_at`, and key counts (theme count, call count). Powers the per-date "version dropdown" in the UI.

**UI.** When the picked date has > 1 run, the date picker reveals a sub-selector ("most recent" + numbered older runs with `recorded_at`). Single-run dates collapse the picker to a single entry, no sub-UI.

## Phase 3 — range mode (designed, not built)

**Aggregation rules (proposed, not hard-coded yet).**

- **Theme persistence**: a theme tag-set is "persistent" if it appears in ≥ N (default 3) of the days in the range. Surface as "AAPL near 52w-high — 5 days running".
- **Strategy fit ranking**: sum (or median, exposed as a toggle) of `today_fit` scores across days; tie-break by number of days the strategy hit ≥ 3.
- **Call surface**: every L3 call ever made in the range, deduped by content hash, sorted by date. Re-issued calls show count.
- **Anomaly frequency**: top-N obs tags by day-count.

**API.** `GET /api/lattice/range?from=YYYY-MM-DD&to=YYYY-MM-DD&project_id=...&persist_threshold=3`. Returns the four aggregates above. Internally iterates `read_snapshot` over each date in range; missing dates are skipped (response includes a `coverage` field so the UI can warn "3 of 7 days missing").

**Why range is non-trivial.** Naively unioning N snapshots gives a noisy mess. We're choosing intersection-with-frequency-weighting because it answers the operator's actual question — "what's been *consistently* true this week", not "everything that ever happened".

## Phase 4 — full bitemporal market data (designed, deferred)

**The gap.** Currently `market_data_daily` PK is `(symbol, market, trade_date)`. Re-fetching the same date overwrites — only the latest fetch's price/volume survives. A snapshot recorded yesterday using older data is **not reproducible** because we lost the older data.

**Fix (when needed).** Add `fetched_at` to PK → `(symbol, market, trade_date, fetched_at)`. Multiple rows per `(symbol, trade_date)`, one per fetch. Point-in-time queries:

```sql
SELECT * FROM market_data_daily
 WHERE symbol='AAPL' AND trade_date='2026-04-25'
   AND fetched_at <= '2026-04-26T03:30:00Z'
 ORDER BY fetched_at DESC LIMIT 1;
```

returns the version of AAPL's 2026-04-25 close that the snapshot at 2026-04-26 03:30 actually saw.

**Why deferred.** Phase 1-3 cover 95% of the operator's use cases. Bitemporal explodes storage (one fetch ≈ 30k rows; daily fetch over 6 months = 5.4M rows) and complicates every query. We pay that cost when an actual reproducibility audit demands it, not preemptively.

## Implementation order

1. **Phase 2 schema first** (snapshot path layout + `read_snapshot` accepts `run_id`) — even though Phase 1 doesn't expose run-level UI, getting the on-disk layout right means Phase 1's writes immediately produce the right shape. No future migration.
2. **Phase 1 backend** — the four endpoints accept `as_of`. Test against the new disk layout.
3. **Phase 1 frontend** — date picker + threading.
4. **Validate** with a manual replay of one day before declaring done.
5. **Phase 3** is its own follow-up and should not be conflated.

## Open questions

- **LIVE-vs-snapshot equivalence**: when `as_of=today's-date`, do we read the snapshot, build live, or both and warn on diff? Current proposal: build live, but write a snapshot at end (same as Phase 0 behaviour). Snapshots act as an immutable audit ledger of past runs, not the current truth.
- **Range mode caching**: aggregating 7 days every request is expensive. Cache by `(from, to, persist_threshold)` for ~5 minutes.
- **Strategy catalog versioning**: the catalog YAML evolves. Should `as_of` also pin to the catalog version that existed at that date? Current answer: no, catalog changes are rare and the operator wants "today's catalog scored against historical themes", not full historical re-evaluation. Re-visit if catalog churn becomes a problem.
