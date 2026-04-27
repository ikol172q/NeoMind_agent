# Provenance-first architecture — final spec

**Date**: 2026-04-26
**Status**: design (final, ready to implement)
**Supersedes**: previous draft of this file
**Builds on**: 2026-04-26_temporal-replay-architecture.md (Phase A as_of single-day shipped)

## Why this document exists

The agent will sometimes be wrong. The user accepts that. What is non-negotiable is **reproducibility**: given a (date, run_id), we must be able to show the exact raw bytes that fed it, the exact prompt sent to which LLM at what temperature, the exact response that came back, and how it was post-processed. If we cannot reproduce, we cannot audit, and the user cannot trust any conclusion.

This document is the agreed spec. Where it conflicts with another doc, this one wins.

## Five foundational invariants

These are non-negotiable. Every implementation decision must obey them.

1. **Immutable provenance.** Nothing the agent ever writes is later modified or deleted. New versions are new files. The user is the only entity that may delete; the agent provides a CLI for inspection but never auto-deletes.

2. **Bitemporal time.** Every datum carries `valid_time` (when the event happened in the world) and `transaction_time` (when we observed/recorded it). Point-in-time queries always specify both.

3. **Strict `dep_hash` cache.** A cached value is reused only if every byte of every input is identical, hashed canonically. "Looks similar" never wins. `dep_hash` includes `code_git_sha`, so any code change invalidates downstream caches; the user accepted the LLM-cost trade-off.

4. **Crawl ≠ Compute ≠ Display.** The three pipelines are decoupled. Fresh raw bytes never auto-mutate a visible result. The user is notified that newer data exists; only an explicit recompute produces a new run_id. Once displayed, a result is pinned to its (date, run_id, dep_hash) and never silently shifts.

5. **Visible breadcrumb everywhere.** Every analysis surface (Research, Strategies, every chip, every popover) shows or links to the (date, run_id, dep_hash) that produced what is being shown. The user can never accidentally read result A while thinking it came from data B.

## Storage layout

All paths relative to `<investment_root>/<project_id>/`.

```
raw/
├── blobs/                                  ← Layer 1: immutable, content-addressed
│   ├── <sha256[:2]>/<sha256>.warc.gz       ← raw bytes, WARC standard format,
│   │                                         gzip-compressed; first 2 chars of hash
│   │                                         are subdirectory (avoids 100k files in
│   │                                         one folder, DVC convention)
│   └── <sha256[:2]>/<sha256>.meta.json     ← {
│                                           │   sha256, size_bytes,
│                                           │   url, response_status, response_headers,
│                                           │   valid_time,            ← when published
│                                           │   first_seen_at,         ← first crawl tx_time
│                                           │   seen_at: [             ← every crawl that hit
│                                           │     {crawl_run_id, tx_time}, ...
│                                           │   ],
│                                           │   prev_version_hash,     ← if URL had a different
│                                           │                            blob earlier (silent edit)
│                                           │   simhash_64,            ← multi-source dedupe key
│                                           │   schema_version: 1
│                                           │ }
├── crawl_runs/
│   └── <YYYY-MM-DD>/                       ← partitioned by tx_time date
│       └── <crawl_run_id>.json             ← which blobs THIS crawl selected, plus
│                                             the readiness/health report
├── crawl_runs/<YYYY-MM-DD>/<crawl_run_id>.report.json
│                                           ← {
│                                           │   totals: {fetched, new, deduped_by_simhash,
│                                           │            superseded, http_4xx, http_5xx},
│                                           │   sample: [
│                                           │     {url, valid_time, first_120_chars, sha256}
│                                           │   ],  ← 5 random blobs for human/LLM spot-check
│                                           │   anomaly_alerts: [...]
│                                           │ }
├── market_data/
│   └── <symbol>/<YYYY>-<MM>.parquet        ← columnar; columns include trade_date,
│                                             fetched_at, valid_from, valid_to.
│                                             Re-fetched rows that differ from the
│                                             prior version → new row (SCD-2 pattern).
└── _index.sqlite                           ← FTS5 over extracted_text + indexes on
                                              (valid_time, tx_time, source, simhash_64)

derived/
├── observations/<YYYY-MM-DD>/<compute_run_id>.json
│                                           ← cites blob sha256s; produced
│                                             deterministically from raw
├── themes/<YYYY-MM-DD>/<compute_run_id>.json
│                                           ← LLM step; cites observation_ids
├── calls/<YYYY-MM-DD>/<compute_run_id>.json
│                                           ← LLM step; cites theme_ids;
│                                             includes prompt template + temperature
│                                             + raw model response verbatim
├── _dep_index.sqlite                       ← (compute_run_id, step, dep_hash, deps,
│                                              created_at) lookup; the cache
├── lineage/<YYYY-MM-DD>/<compute_run_id>.openlineage.jsonl
│                                           ← optional OpenLineage event stream;
│                                             one JSONL per pipeline step

snapshots/<YYYY-MM-DD>/<snapshot_run_id>.json
                                           ← Layer 3: the presentation envelope
                                             tying together raw + derived bundles
                                             for one display state. Includes the
                                             ValidationReport (7-step, see below).

snapshots/<YYYY-MM-DD>/<snapshot_run_id>__replay_of_<orig>.json
                                           ← when "Replay" produces a different
                                             output than the original; both stored.

notifications/pending.json                  ← single small JSON, polled by UI every 30s
notifications/audit.jsonl                   ← every notification (dismissed or acted on)
                                              appended for audit trail
```

### Why WARC for blobs

We adopt WARC (Web ARChive, IETF / Library of Congress standard) as the on-disk format for every fetched blob. Reasoning:

- **Standardised header set**: URL, response status, response headers, fetch timestamp, content type are all named fields in the spec. We cannot accidentally lose a field by forgetting to include it.
- **Library-supported reading**: `warcio` Python library (small, mature, no service) reads/writes. Future tools (pywb, Wayback) can read our archive.
- **Single-file containers**: WARC bundles request + response + headers, perfect content-addressed unit.
- **Zero runtime dependency**: just a Python library, no service.

We do NOT adopt ArchiveBox or Browsertrix as services — they do too much (PNG/PDF rendering, recursive crawling) and are over-engineered for our use case. We borrow only the format.

### Multi-source dedupe (SimHash)

When we crawl, we calculate a 64-bit SimHash over the canonicalised article text. We store all raw blobs (immutability), but the COMPUTE pipeline uses SimHash to detect that 4 URLs are the same fact wire-reposted, and merges them into one observation with a `merged_into: <canonical_blob_hash>` field on the suppressed three. The lattice graph then shows 1 obs node with a `×4 sources` badge; click expands to the 4 URLs.

Per operator instruction: **dedupe only, no confidence weighting** at first. A `confidence_boost_for_multi_source` field is reserved in the schema (defaulted to `false`) so we can flip it on later without migration.

## Crawl ↔ Compute ↔ Display separation (the core UX)

```
┌────────────────────────────────────────────────────────────┐
│  Crawl pipeline (background or scheduled)                  │
│  - fetches bytes → writes blobs/ + crawl_runs/             │
│  - emits readiness report + 5-sample for spot-check        │
│  - never touches derived/ or snapshots/                    │
│  - on success: appends to notifications/pending.json       │
└────────────────────┬───────────────────────────────────────┘
                     │  (does not propagate automatically)
                     ▼
              ┌──────────────────┐
              │ notification:    │
              │ "new crawl_run   │
              │  available; LLM  │
              │  one-line summary│
              │  of what it has" │
              └──────┬───────────┘
                     │  user clicks "Re-run analysis"
                     │  (or scheduled cron, opt-in only)
                     ▼
┌────────────────────────────────────────────────────────────┐
│  Compute pipeline (explicit)                               │
│  - reads chosen crawl_run + sample strategy                │
│  - dep_hash; cache lookup; if hit, return same compute_run │
│  - else: observations → themes → calls (LLM)               │
│  - per-step ValidationReport                               │
│  - writes derived/ + snapshots/                            │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────┐
│  Display                                                   │
│  - reads snapshots/<date>/<run_id>.json                    │
│  - permanent breadcrumb (date, run_id, dep_hash, sources,  │
│    LLM model + temperature + tx_time)                      │
│  - never auto-refreshes; manual refresh only               │
│  - status floating panel (right-bottom): in-flight runs,   │
│    ready runs, displayed-vs-latest coherence indicator     │
└────────────────────────────────────────────────────────────┘
```

Default behaviour:
- Scheduler crawls; **does not** auto-compute. (Operator confirmed.)
- Compute runs only on user click or on an explicit opt-in cron.
- LLM-cost-incurring steps (themes, calls) never fire silently.

## `dep_hash` composition

```
dep_hash = sha256_hex(
  "v1|"                                          ← the hash scheme version
+ sorted_join(blob.sha256 for blob in inputs)
+ "|" + prompt_template_version
+ "|" + llm_model_id + "@" + str(temperature)
+ "|" + sample_strategy_serialized              ← e.g. "top_n_relevance:30:seed=4711"
+ "|" + taxonomy_version
+ "|" + code_git_sha                            ← short sha (8 chars enough)
)
```

Strict mode is non-negotiable per operator instruction. Cost mitigation:
- The cache will hit when **nothing** changes, so identical-input identical-code reruns are free.
- A diagnostic CLI prints "dep_hash differs because: <field>" to make cost causes visible.

## UI surfaces (5 places)

### 1. Top-nav AsOfPicker (already shipped Phase A)
Add: when a date is picked, show count of compute_runs available for that date as a small superscript number; click to expand into a per-run sub-selector.

### 2. Freshness Bar (per-tab, top of body)
On Research and Strategies tabs:
```
📅 2026-04-23 · 🏷 run abc123 · 🧠 deepseek-v4-flash @ T=0.3 · 📰 30/200 raw items · ⚙ dep_hash 4f2c…
✓ data-coherent: this view = compute(crawl xy7z + market m4)
🟡 1 newer crawl run since this compute (dismiss / re-run)
🟢 7/7 validation steps pass
```
Click any segment → drill down. Date → date picker. run_id → run history. dep_hash → dependency tree panel. 📰 → list source URLs (each is a hyperlink). LLM → Langfuse-style trace view (self-built, see below).

### 3. Status Floating Panel (right-bottom, draggable, foldable)
Persistent across tabs. Operator confirmed: **draggable, foldable to small icon, hyperlinks click-through**.
```
┌──────────────────────────────────┐
│ ⏵ crawl: news.yfinance running  │ ← link → live progress
│ ✓ market_data: ready (3m ago)    │ ← link → that crawl_run report
│ ⏵ compute: lattice run-xyz123   │ ← link → in-progress dep tree
│ ⚠ Strategies tab is stale       │ ← link → "Re-run analysis"
│   (data: 04-23, displayed: 04-23 │
│    but newer crawl 04-26 exists) │
└──────────────────────────────────┘
                              [_]  ← collapse
```

States derived from `notifications/pending.json` polled every 30s.

### 4. Data Lake tab (NEW)
Operator-confirmed addition. Three sub-views:

- **Crawl Runs** — table by date, expandable to per-run report (totals, sample, anomaly alerts). Differentiates by icon: 📈 expansion, 📜 backfill, 🔁 forced refresh. Each row links to the underlying blobs.
- **Compute Runs** — table tied to a crawl_run, listing each compute attempt + its sample strategy + its dep_hash + its outputs (theme count, call count, LLM cost, duration).
- **Replay Diffs** — when a Replay produces a non-byte-identical output, both runs are listed side-by-side with the step-level mismatch indicator (item-level diff on click).

### 5. Existing Audit tab "PAST RUNS" (keep)
Adds the run-type toggle: scheduler runs / crawl runs / compute runs. Cross-link to Data Lake.

## Sample strategies (4 modes)

User selects on each compute trigger; default in Settings.

| Mode | Determinism | Notes |
|---|---|---|
| `all` | yes | Use every available item; no sampling. |
| `top_n_relevance:N` | yes (relevance score is deterministic from raw + scoring code version) | Default. N selects from highest score. |
| `random:N:seed=SEED` | yes (seed in dep_hash) | Stratified or simple random; seed surfaced in breadcrumb. |
| `time_window:H_hours:N` | yes | Last H hours by valid_time, top-N by relevance within. |

Sample strategy is part of `dep_hash` so two compute runs with different samples always get distinct compute_run_ids.

## Replay vs Read

Two paths to view a date:

- **Read** (default): UI loads `snapshots/<date>/<run_id>.json`. Fast.
- **Replay**: UI button on a snapshot triggers re-execution of the pipeline reading the SAME raw blobs and SAME settings (prompt version, model, sample seed) the original snapshot recorded. We then compare:
  - If byte-identical → success badge + "reproducibility verified".
  - If different → warn alert + write the new outcome as `<orig>__replay_of_<orig>.json`, link the two for diff viewing. Step-level diff table shows where the divergence started.

LLM nondeterminism (temperature > 0, provider-side variance) will frequently produce non-identical replays. We surface this as a fact, not a failure: the user learns "this LLM call is 70% reproducible" and decides if that matters.

## Validation framework — 7 pipeline steps

Per operator instruction: `fail` shows red badge but does NOT block.

| # | Step | Owner | Critical checks |
|---|---|---|---|
| 1 | Collect | Crawler | response 2xx; content_length > N; charset detected; rate-limit honoured; supersedes report |
| 2 | Save | RawStore | sha256 of bytes equals filename; meta.json valid; FTS5 row inserted |
| 3 | Load | RawStore reader | sha256 of read bytes equals expected (silent disk corruption check) |
| 4 | Algorithm | Observation builder, deterministic | bit-identical when re-run on same input; obs_id stability |
| 5 | LLM | Theme/call generator | response valid JSON; matches Pydantic schema; cited_numbers exist verbatim in input; fallback narrative ≠ silent success |
| 6 | Distill | Aggregator | every theme.grounds resolves; every call.grounds resolves; counts within historical p10–p90 |
| 7 | Visualize | UI | every chip data-source resolves to real backend value (already implemented) |

Anomaly detector: per-step metric stored in `_dep_index.sqlite`. Rolling p10/p90 over last N successful runs. Outliers flagged; UI shows the alert; user proceeds or aborts.

States borrowed from Dagster: `PASS / WARN / FAIL / UNKNOWN`. Naming consistency lets us optionally emit OpenLineage events and inter-operate with that ecosystem later.

## Compute granularity (per operator answer)

The "Re-run analysis" button is a split-button:
- **Default click**: re-run the full pipeline (observations → themes → calls).
- **Drop-down**: re-run from a specific step. Earlier steps' cache is reused (gated on dep_hash). E.g., "re-run themes only — keeps observations cached, regenerates LLM narratives, recomputes calls."

A right-click on a single L2 theme node → "regenerate this narrative only" is a stretch goal (B11+).

## What we adopt from existing tools (decision matrix)

| Tool | Risk | Decision |
|---|---|---|
| **WARC + warcio** | None — pure Python library, no service | ✅ Adopt |
| **Langfuse self-host** | High — needs Postgres + ClickHouse + Redis + S3 services; outage breaks LLM step; multi-team features wasted on single-user | ❌ Reject. Self-write LLM trace to `derived/calls/<run_id>.json`. |
| **DVC** | Medium — strong git coupling, doesn't fit our date-partitioned model | ❌ Reject. Borrow only the design pattern (content addressing, MD5 prefix subdirectories). |
| **Dagster** | High — full orchestration platform | ❌ Reject. Borrow only freshness 4-state vocabulary (PASS/WARN/FAIL/UNKNOWN) for naming consistency. |
| **XTDB** | High — JVM + RocksDB + Kafka, foreign stack | ❌ Reject. Borrow only bitemporal query semantics, implement on SQLite indexes. |
| **ArchiveBox / Browsertrix** | Medium — independent Docker services, over-feature for our minimal needs | ❌ Reject. Self-write minimal fetcher with `requests + warcio`. |
| **OpenLineage** | None — open event spec, no service | 🟡 Optional in B7. Emit alongside derived files; future-proof for DataHub integration. |
| **dbt SCD-2 patterns** | None — design pattern only | ✅ Borrow. Apply to market_data parquet. |

**Net dependency change**: one new pip package (`warcio`). Zero new services. Zero new failure modes that aren't already in our Python process.

## Phasing — 10 build steps, B1 → B10

| # | Phase | Scope | LOC |
|---|---|---|---|
| B1 | Raw store skeleton | `raw/blobs/` WARC writer + meta.json + sha256 index + FTS5 | 250 |
| B2 | Bitemporal columns | `valid_time` + `tx_time` everywhere + indexes | 150 |
| B3 | Crawler reroute | every existing crawler writes via RawStore + crawl_run_id | 300 |
| B4 | dep_hash + strict cache | per-step dep_hash + `_dep_index.sqlite` + cache lookup gate | 200 |
| B5 | Compute pipeline split | `derived/{observations,themes,calls}/<date>/<compute_run_id>.json` | 200 |
| B6 | Notifications + breadcrumb + Status panel | `notifications/pending.json` + UI poll + Freshness Bar + Floating Status | 350 |
| B7 | Validation framework | 7-step ValidationReport + anomaly detector + p10/p90 | 350 |
| B8 | Range mode | `/api/lattice/range?from=&to=` + UI | 350 |
| B9 | Replay vs Read | "Replay" button + step-level diff renderer | 200 |
| B10 | Storage tiers | (operator-deferred; not auto-deletion ever) | 200 |

Recommended order: B1 → B2 → B3 → B4 → B5 → B6 are the **trust core** (~1450 LOC). After B6 the operator can already trust every visible result. B7-B10 polish.

## Open question (operator hasn't decided yet, low priority)

- **OpenLineage emitter** — emit alongside derived files (zero risk, no service)? Or skip for now? My recommendation: skip until B7+. We can retroactively re-emit from derived files.

If you have no objection to OpenLineage = skip-for-now, I will start B1.
