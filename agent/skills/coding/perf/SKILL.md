---
name: perf
description: Performance benchmarking — identify critical paths, measure load/memory/response, compare baseline, report trends
modes: [coding]
allowed-tools: [Bash, Read, Edit, WebSearch]
version: 1.0.0
---

# Perf — Performance Benchmarking

You are the performance engineer. Mission: identify bottlenecks, measure metrics, compare with baseline, recommend optimizations.

## Workflow

### 1. Identify Performance-Critical Paths

Ask:
- Which code paths are hit most frequently?
- Which operations are user-facing (affect perceived latency)?
- Which operations consume the most resources?
- What's the current bottleneck?

**Tools:**
- Profiling: `cProfile` (Python), `perf` (JavaScript), `pprof` (Go)
- Flame graphs: visualize where time is spent
- Trace analysis: follow execution flow

### 2. Measure Baseline Metrics

**For CLI/Backend:**
- Load time: `time python script.py` (multiple runs, average)
- Memory usage: `memory_profiler`, `tracemalloc`
- Response time per operation: benchmark each critical function
- Database queries: log query count and total time
- CPU usage: `top`, `htop`, profiler output

**For Web Apps (use browser daemon):**
- Page load time: `browse goto <url>` + measure document ready time
- Core Web Vitals:
  - LCP (Largest Contentful Paint): time for main content to appear
  - FID (First Input Delay): responsiveness to user input
  - CLS (Cumulative Layout Shift): visual stability
- Time to Interactive (TTI): when page becomes interactive
- JavaScript execution time: `browse js "console.time()" / "console.timeEnd()"`

**Command Examples:**
```bash
# Python: benchmark function
python -m timeit -n 1000 "my_function()"

# Node.js: benchmark
node --expose-gc benchmark.js

# Database: query profiling
EXPLAIN ANALYZE SELECT * FROM table;
```

### 3. Use Browser Daemon for Core Web Vitals (if web app)

```bash
browse goto https://myapp.com
browse screenshot /tmp/before.png
browse js "document.readyState; window.performance.timing"
```

Take measurements:
- Time from navigation to First Contentful Paint (FCP)
- Time from navigation to Largest Contentful Paint (LCP)
- Cumulative Layout Shift score
- JavaScript bundle size

### 4. Compare with Previous Baseline

Get previous measurements from:
- `~/.neomind/evidence/perf-baseline-<component>.txt`
- Git history: `git log --all --oneline -- perf-results.txt`

Calculate deltas:
```
Metric                 Old        New        Change
─────────────────────────────────────────────────────
Page Load Time        2.5s       2.1s       ↓ 16%
Memory Usage          256MB      189MB      ↓ 26%
DB Query Time         145ms      98ms       ↓ 32%
JS Bundle Size        512KB      486KB      ↓ 5%
```

Determine: Is this improvement or regression?
- ✅ Improvement: < previous measurement
- ❌ Regression: > previous measurement

### 5. Report: Metrics Table + Trend + Bottleneck Analysis

**Report Format:**
```
PERFORMANCE BENCHMARK REPORT
────────────────────────────
Component: [name]
Date: [YYYY-MM-DD]
Environment: [OS, Node version, Python version, etc.]

BASELINE METRICS
────────────────
Metric                    Measurement    Unit       Target
─────────────────────────────────────────────────────────
Page Load Time            2.1s           seconds    < 3s ✅
Largest Contentful Paint  1.8s           seconds    < 2.5s ✅
First Input Delay         45ms           ms         < 100ms ✅
Memory Peak               189MB          MB         < 250MB ✅
DB Query Time             98ms           ms         < 150ms ✅
JavaScript Bundle         486KB          KB         < 500KB ✅

TREND ANALYSIS (vs previous baseline)
─────────────────────────────────────
Metric              Previous    Current    Δ       Status
─────────────────────────────────────────────────────
Load Time          2.5s        2.1s       ↓ 16%   ✅ Improved
Memory Usage       256MB       189MB      ↓ 26%   ✅ Improved
DB Queries         145ms       98ms       ↓ 32%   ✅ Improved

BOTTLENECK ANALYSIS
────────────────────
Top 3 resource consumers (by CPU time):
  1. database_query_handler: 42% of total time
  2. json_serialization: 18% of total time
  3. image_resize: 12% of total time

Recommendations:
  - Add database query caching (could save ~25ms per request)
  - Optimize JSON encoder (consider ijson or faster alternative)
  - Lazy-load images instead of processing on page load

NEXT STEPS:
  [ ] Apply recommendation #1: database caching
  [ ] Re-benchmark after optimization
  [ ] Track improvements in weekly perf dashboard
```

## Rules

- **Always measure twice**: One warm-up run, then measure (avoid cold-start bias)
- **Multiple samples**: Average over 10+ runs for stability
- **Same conditions**: Same hardware, network, workload each time
- **Save baseline**: Store in `~/.neomind/evidence/` for future comparison
- **Target-driven**: Have a performance target (e.g., < 3s load time) before measuring
- **Profile before optimizing**: Don't guess where time is spent — profile first

## Tools Recommendation

| Language   | Profiler          | Memory Profiler      | Web Vitals        |
|------------|-------------------|----------------------|-------------------|
| Python     | cProfile, scalene | memory_profiler      | N/A               |
| JavaScript | `console.profile` | Chrome DevTools      | web-vitals lib    |
| Go         | pprof             | pprof                | N/A               |
| Java       | JProfiler         | Eclipse MAT          | N/A               |
