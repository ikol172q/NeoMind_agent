# Insight Lattice — build status as of 2026-04-24

Current-state snapshot of the Insight Lattice pipeline + UI.
Complements (does not replace) the original design docs:

- [2026-04-20_insight-lattice.md](2026-04-20_insight-lattice.md) — original spec (n=3, overlap-preserving, `cites:` chain)
- [2026-04-22_lattice-validation.md](2026-04-22_lattice-validation.md) — validator contracts

The pipeline is running in production on `fin-core` against live
DeepSeek / LLM-Router traffic. This file is the "where we are" memo
for anyone picking it up cold.

---

## 1. Pipeline in one paragraph

Dashboard widgets (**L0**) emit typed signals via generator functions
→ a per-kind L1 generator turns them into first-class
`Observation`s (**L1**) → MMR-diversified clustering groups
observations into sub-themes (**L1.5**) → sub-themes are promoted to
themes (**L2**) with an LLM-written narrative → a Toulmin-style
clusterer emits ≤3 actionable `Call`s (**L3**) with `grounds` that
must cite real L2 theme ids. Every step is cached per
`(language, budget_hash, project)` and every LLM output is
validator-gated; a validator rejection falls back to deterministic
output with a bounded `drop_reason`.

## 2. What's built (V1 → V13)

| Version | Area | What shipped |
|---|---|---|
| V1 | backend | `spec.py` + L1 spec-contract + L2 formula tests |
| V2 | backend | `/api/lattice/graph` + L3/L4 coherence |
| V3 | UI | Interactive SVG lattice viz + trace panel |
| V4 | infra | Fixture drift detection + pre-commit hook |
| V5 | backend | Bilingual output (zh-CN-mixed) via YAML switch |
| V6 | UI | Deep trace + language toggle button |
| V7 | UI | Zoom/pan + `layer_budgets` + L1→L0 jump |
| V8 | backend | Daily lattice snapshot + historical view (`past` button) |
| V9 | backend+UI | Runtime `layer_budgets` override + picker |
| V10 | all | A1 column header `?` explainers · A2 self-check endpoint + integrity badge · A3 raw L0 payload in trace |
| V11 | UI | Hide dashboard widgets; lattice becomes Research's single focus. Widgets moved to `Legacy` tab (accessible via Settings card or `?legacy=1`). |
| V12 | UI | Config drawer (gear) with watchlist + portfolio editors · L0 nodes get curated external links (TradingView / Yahoo / Finviz / 雪球 / OpenBB / EarningsWhispers / CNN F&G / AAII) |
| V13 | UI | Trackpad-friendly pan: plain wheel / two-finger swipe pans · ctrl+wheel / pinch zooms · drag still works |

## 3. Key file map

### Backend (Python)

- `agent/finance/lattice/spec.py` — data classes, `final_membership_weight()`, invariants
- `agent/finance/lattice/taxonomy.py` — YAML loader (kind taxonomy, output_language, budget defaults)
- `agent/finance/lattice/observations.py` — L0 → L1 generators, per-kind filters
- `agent/finance/lattice/themes.py` — L1 → L1.5 → L2, MMR clustering, narrative LLM + validator
- `agent/finance/lattice/calls.py` — L2 → L3 Toulmin calls, grounds validation
- `agent/finance/lattice/graph.py` — `/api/lattice/graph` wire format
- `agent/finance/lattice/router.py` — FastAPI endpoints (all under `/api/lattice/*`)
- `agent/finance/lattice/runtime.py` — language + budget override state, `budget_hash()`
- `agent/finance/lattice/selfcheck.py` — V10·A2 live integrity check (5 invariants)
- `agent/finance/lattice/snapshots.py` — V8 daily-snapshot read/write

### Frontend (React/TS, served by `dashboard_server.py`)

- `web/src/tabs/Research.tsx` — lattice-only Research tab (wraps `<DigestView>` + `<ResearchConfigDrawer>`)
- `web/src/tabs/Legacy.tsx` — widget-grid fallback (V11; `?legacy=1`)
- `web/src/tabs/Settings.tsx` — has card to open Legacy
- `web/src/components/widgets/DigestView.tsx` — header toolbar (past / check / budgets / language / refresh / config), mode switcher (Summary / Detail / Focus / Trace), hosts `<LatticeGraphView>` in Trace mode
- `web/src/components/widgets/LatticeGraphView.tsx` — SVG lattice (columns + edges), zoom/pan, click-to-trace
- `web/src/components/widgets/LatticeTracePanel.tsx` — per-node trace details (citations, raw payloads, external links, L1→L0 jump)
- `web/src/components/widgets/ResearchConfigDrawer.tsx` — right-side drawer, watchlist + portfolio editors (V12)
- `web/src/lib/api.ts` — typed client wrappers

### Tests

- `tests/test_lattice_*.py` — unit & invariant tests per layer
- `tests/test_lattice_runtime_budgets.py` — V9 budget-override coverage
- `tests/test_lattice_selfcheck.py` — V10·A2 self-check endpoint
- `tests/test_lattice_snapshots.py` — V8 snapshot read/write
- `tests/test_web_zoom_and_jump.py` — pan/zoom math + L1→L0 selector
- `/tmp/e2e_v*.py` (ephemeral) — playwright walkthroughs; not committed (cheap to regenerate)

## 4. Caching / language / budgets

- All router endpoints key cache on `(effective_language, budget_hash, project_id)`.
- Language toggle is a pointer flip: first fetch in each language pays the LLM cost; subsequent toggles between already-seen languages are cache hits.
- Budget knob values are free-form ints per layer; any change busts only the affected language/budget cells, not every project.
- Snapshots are written to `<investment_root>/<project_id>/lattice_snapshots/<YYYY-MM-DD>.json` on every fresh build.

## 5. The validate-then-ship contract (non-negotiable)

Every LLM output (narratives, calls) goes through a deterministic
validator **before** any downstream code reads it. Validator rejects
produce a `drop_reason` (bounded set of reasons) and fall back to
deterministic output. This is why the self-check endpoint can exist:
every stored output has already passed the same gate the self-check
re-runs. See
[2026-04-23-validate-then-ship-llm-pattern.md](../.claude/docs/troubleshooting/2026-04-23-validate-then-ship-llm-pattern.md).

## 6. Troubleshooting anti-patterns captured

In `.claude/docs/troubleshooting/`:

- `2026-04-23-svg-viewbox-transform-voodoo.md` — why we moved from SVG viewBox to CSS transform on a wrapper `<div>`
- `2026-04-23-pan-clamp-on-canvas-not-content.md` — clamp on node bbox, not canvas, or you park on empty gaps
- `2026-04-23-drag-listener-useeffect-race.md` — mousedown-useEffect gap drops mouseup; attach synchronously
- `2026-04-23-ui-bug-ship-without-browser-test.md` — after 3 failed patches, stop editing and write a repro
- `2026-04-23-validate-then-ship-llm-pattern.md` — the LLM-validator contract
- `2026-04-24-dashboard-features-that-compete-with-public-products.md` — why V11 killed the widget grid in Research
- `2026-04-24-useeffect-ref-race-with-early-returns.md` — `useEffect(..., [])` + `ref.current` + early-return loading state = silently no listener; mirror the DOM node into state

## 7. Pending / deferred (explicit)

- **#105 · Call stability (hysteresis / EMA)** — DEFERRED past D6, pending a targeted research round. Today a call can flicker in/out day-over-day if the underlying themes wobble; we don't smooth over history yet.
- **#106 · Shift-click LLM explainer** — DEFERRED. Idea: shift-click a node → on-demand LLM explains *why this node was promoted / what it means for today*. Low priority; trace panel already surfaces the deterministic reasoning.

Nothing else pending at the Lattice scope.

## 8. Known "by design" limitations

- L3 allows 0 calls. "No high-conviction action today" is a legitimate output; forced emission corrupts trust.
- Middle layer count `n` is config-driven (currently 3, 4 wired behind `sub_themes_n=4` YAML switch, off by default).
- L0 is a *tagging + snapshot* pipeline, not a viewing product. Users follow external links (TradingView/Yahoo/Finviz/雪球) for the chart/heatmap/earnings calendar *experience*. See the troubleshooting doc above.

## 9. How to continue

Next productive moves, roughly in priority order:

1. **Address #105 call-stability** if the user notices day-to-day flicker in the L3 calls. The original plan mentions EMA over the last N days of snapshots — the V8 snapshot pipeline makes that cheap to implement now.
2. **Seed more symbols** into the watchlist / portfolio if the lattice still over-indexes on AAPL/AMD/ARM/META/MSFT (current scope set 2026-04-24).
3. **Shift-click explainer (#106)** if the user asks "why was this promoted?" — the trace panel is deterministic, an LLM explainer would be the narrative-friendly counterpart.

Do **not**:

- Re-introduce widget tiles into Research. That was explicitly reversed in V11.
- Add new L0 tiles without asking whether the public product (TradingView etc.) does it better — default to linking out.
- Write LLM output straight through without the validator gate.
