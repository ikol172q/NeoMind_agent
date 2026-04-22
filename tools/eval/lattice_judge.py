#!/usr/bin/env python3
"""LLM-as-judge evaluator for Insight Lattice L1 observations.

Research-backed design (see plans/2026-04-20_insight-lattice.md §A):
- **G-Eval style** rubric-in-prompt with chain-of-thought scoring.
- **Self-consistency N=3**: three judge calls per observation at
  T≈0.3; take the median. Research shows this halves judge variance
  at ~3× cost — within budget for ≤40 obs per scenario.
- **Four axes**: Specificity, Actionability, Novelty, Noise (each
  1–5 Likert).
- **Fixed scenarios** (empty, thin, mid, rich, drawdown, iv-heavy)
  so runs are comparable over time — drift detection.
- **Output**: structured JSON report + human-readable markdown.
  Flags observations that score low on any axis, separately from
  aggregate stability.

Run:
    .venv/bin/python tools/eval/lattice_judge.py
    .venv/bin/python tools/eval/lattice_judge.py --scenarios rich
    .venv/bin/python tools/eval/lattice_judge.py --n 5 --report /tmp/out.md
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
import urllib.error
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

BASE_URL = os.environ.get("NEOMIND_DASHBOARD_URL", "http://127.0.0.1:8001/")
PROJECT = os.environ.get("NEOMIND_PROJECT", "fin-core")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
JUDGE_MODEL = "deepseek-chat"


# ── Scenarios — seed controllable L1 state ─────────────

@dataclass
class Scenario:
    name: str
    description: str
    watchlist: List[tuple[str, str]]   # [(symbol, market), ...]
    positions: List[tuple[str, int]]   # [(symbol, qty), ...]


SCENARIOS: List[Scenario] = [
    Scenario(
        "empty",
        "No watchlist, no positions. Baseline: only market-level obs should fire.",
        watchlist=[],
        positions=[],
    ),
    Scenario(
        "thin",
        "One watchlist symbol, one position. Minimum viable state.",
        watchlist=[("AAPL", "US")],
        positions=[("AAPL", 5)],
    ),
    Scenario(
        "mid",
        "4 watchlist + 2 positions, mixed sectors.",
        watchlist=[("AAPL", "US"), ("NVDA", "US"), ("XOM", "US"), ("JPM", "US")],
        positions=[("AAPL", 5), ("NVDA", 3)],
    ),
    Scenario(
        "rich",
        "8 watchlist + 3 positions, cross-sector diverse basket.",
        watchlist=[("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US"), ("GOOGL", "US"),
                   ("TSLA", "US"), ("XOM", "US"), ("JPM", "US"), ("UNH", "US")],
        positions=[("AAPL", 5), ("NVDA", 3), ("TSLA", 2)],
    ),
    Scenario(
        "iv_heavy",
        "Symbols with upcoming earnings, testing IV signal density.",
        watchlist=[("TSLA", "US"), ("MSFT", "US"), ("META", "US"), ("GOOGL", "US")],
        positions=[("TSLA", 2), ("MSFT", 3)],
    ),
]


# ── REST helpers ───────────────────────────────────────

def _get(path: str, timeout: float = 120) -> Any:
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def _post(path: str, body: Optional[dict] = None, timeout: float = 10) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        try:
            return json.loads(raw) if raw else None
        except Exception:
            return None


def _delete(path: str, timeout: float = 5) -> None:
    req = urllib.request.Request(BASE_URL + path, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:
        pass


def reset_project() -> None:
    """Clear watchlist + paper state."""
    try:
        wl = _get(f"api/watchlist?project_id={PROJECT}", timeout=3)
        for e in wl.get("entries", []):
            _delete(f"api/watchlist/{e['symbol']}?project_id={PROJECT}&market={e['market']}")
    except Exception:
        pass
    _post(f"api/paper/reset?project_id={PROJECT}&confirm=yes")


def seed_scenario(sc: Scenario) -> None:
    reset_project()
    for sym, market in sc.watchlist:
        _post(
            f"api/watchlist?project_id={PROJECT}",
            body={"symbol": sym, "market": market, "note": ""},
        )
    for sym, qty in sc.positions:
        qs = urlencode({
            "project_id": PROJECT, "symbol": sym, "side": "buy",
            "quantity": qty, "order_type": "market",
        })
        _post(f"api/paper/order?{qs}")
    if sc.positions:
        _post(f"api/paper/refresh?project_id={PROJECT}")


def fetch_observations() -> List[Dict[str, Any]]:
    d = _get(f"api/lattice/observations?project_id={PROJECT}&fresh=1", timeout=180)
    return d["observations"]


# ── Judge prompts ──────────────────────────────────────

_JUDGE_SYSTEM = (
    "You evaluate L1 atomic facts inside a layered distillation system. "
    "L1 is NOT user-facing prose; it is structured input for L2 clustering. "
    "Judge each fact on whether it's a USEFUL INPUT TO CLUSTERING — not on "
    "whether a human would find it novel. A clean, tagged, verifiable fact "
    "scores high even if it 'just restates' a widget, because L2 needs raw "
    "facts to cluster. Penalise only facts that are: vague, missing context, "
    "mis-tagged, duplicates of another fact in the same run, or near-zero "
    "signal (e.g. a sector that barely moved). "
    "Respond in JSON only, no prose outside the object."
)

_JUDGE_RUBRIC = """
Score each observation 1-5 on these four axes. L1 is INFRASTRUCTURE,
not output — keep that frame.

SPECIFICITY (is the claim concrete enough to be clustered?):
  5 = cites a specific ticker/sector + specific number + time frame; L2
      can route it precisely
  3 = cites one of: ticker / number / time frame
  1 = vague; L2 cannot route it

TAG_FIT (do the tags accurately describe the fact?):
  5 = every tag is correct; covers every relevant axis (symbol, sector,
      risk, technical, timescale, signal where applicable)
  3 = tags correct but incomplete — some themes will miss this fact
  1 = tags are wrong or contradict the text

UNIQUENESS (does this fact add information vs OTHER FACTS in this run?):
  5 = unique signal; no other fact in this batch says the same thing
  3 = partial overlap with another fact (e.g. both cite the same ticker
      but different angles)
  1 = near-duplicate of another fact in the batch

SIGNAL_STRENGTH (is the underlying number worth reporting?):
  5 = the move/fact is materially important (e.g. >1% sector move,
      IV >1.5× historical, earnings <=7d, position >5% drawdown)
  3 = moderate — would be interesting in some market state
  1 = noise; movement/state is within normal daily variance

Note: "NOVELTY vs raw widget" is NOT an axis here. L1 legitimately
restates widget values; that's its job. The interesting novelty lives
at L2/L3.

For each observation, output:
  {"id": "...", "specificity": N, "tag_fit": N, "uniqueness": N,
   "signal_strength": N, "critique": "≤20 words on why this score"}
"""

def _judge_prompt(obs: List[Dict[str, Any]]) -> str:
    minimal = [
        {"id": o["id"], "kind": o["kind"], "text": o["text"],
         "tags": o["tags"], "severity": o["severity"]}
        for o in obs
    ]
    return (
        _JUDGE_RUBRIC
        + "\n\nOBSERVATIONS TO SCORE:\n"
        + json.dumps(minimal, indent=1)
        + '\n\nReply with {"scores": [ {...}, ... ]}'
    )


def _judge_call(prompt: str, temperature: float = 0.3, timeout: float = 120) -> Dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY missing — run scripts/sync_launchd_env.sh")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            DEEPSEEK_URL,
            json={
                "model": JUDGE_MODEL,
                "messages": [
                    {"role": "system", "content": _JUDGE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": 3000,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek {resp.status_code}: {resp.text[:200]}")
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _batched_judge(obs: List[Dict[str, Any]], temperature: float, batch_size: int = 12) -> List[Dict[str, Any]]:
    """DeepSeek times out on a single prompt over ~15 observations
    because max_tokens burns through the full reply. Split into
    batches and merge results."""
    out: List[Dict[str, Any]] = []
    for i in range(0, len(obs), batch_size):
        chunk = obs[i:i + batch_size]
        try:
            reply = _judge_call(_judge_prompt(chunk), temperature=temperature)
            out.extend(reply.get("scores") or [])
        except Exception as exc:
            print(f"    [batch {i // batch_size + 1} FAILED: {exc}]")
    return out


def judge_observations(
    observations: List[Dict[str, Any]],
    n_samples: int = 3,
) -> Dict[str, Dict[str, Any]]:
    """Self-consistency N=3: call the judge N times, aggregate median."""
    if not observations:
        return {}

    samples: List[List[Dict[str, Any]]] = []
    for i in range(n_samples):
        try:
            scores = _batched_judge(observations, temperature=0.3)
            if scores:
                samples.append(scores)
        except Exception as exc:
            print(f"  [judge pass {i+1}/{n_samples} FAILED: {exc}]")

    if not samples:
        return {}

    axes = ("specificity", "tag_fit", "uniqueness", "signal_strength")
    by_id: Dict[str, Dict[str, List[Any]]] = {
        o["id"]: {axis: [] for axis in axes} | {"critique": []}
        for o in observations
    }
    for sample in samples:
        for score in sample:
            oid = score.get("id")
            if oid not in by_id:
                continue
            for axis in axes:
                v = score.get(axis)
                if isinstance(v, (int, float)):
                    by_id[oid][axis].append(float(v))
            if score.get("critique"):
                by_id[oid]["critique"].append(str(score["critique"]))

    aggregate: Dict[str, Dict[str, Any]] = {}
    for oid, bag in by_id.items():
        row: Dict[str, Any] = {}
        for axis in axes:
            vals = bag[axis]
            row[axis] = round(statistics.median(vals), 2) if vals else None
            row[f"{axis}_stdev"] = round(statistics.stdev(vals), 2) if len(vals) >= 2 else 0.0
        row["sample_count"] = len(bag["specificity"])
        row["critique"] = bag["critique"][0] if bag["critique"] else ""
        aggregate[oid] = row
    return aggregate


# ── Reporting ──────────────────────────────────────────

def summarize_run(
    scenario: Scenario,
    observations: List[Dict[str, Any]],
    scores: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate summary stats + problem list."""
    specs = [s["specificity"] for s in scores.values() if s.get("specificity") is not None]
    tags = [s["tag_fit"] for s in scores.values() if s.get("tag_fit") is not None]
    uniqs = [s["uniqueness"] for s in scores.values() if s.get("uniqueness") is not None]
    sigs = [s["signal_strength"] for s in scores.values() if s.get("signal_strength") is not None]

    def _avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    problems: List[Dict[str, Any]] = []
    for obs in observations:
        s = scores.get(obs["id"], {})
        if not s:
            continue
        issues = []
        # Hard thresholds below which an obs probably shouldn't exist
        if (s.get("specificity") or 5) <= 2:
            issues.append(f"low specificity ({s['specificity']})")
        if (s.get("tag_fit") or 5) <= 2:
            issues.append(f"poor tag_fit ({s['tag_fit']})")
        if (s.get("uniqueness") or 5) <= 2:
            issues.append(f"low uniqueness ({s['uniqueness']}) — duplicates another obs")
        if (s.get("signal_strength") or 5) <= 2:
            issues.append(f"weak signal ({s['signal_strength']})")
        if issues:
            problems.append({
                "kind": obs["kind"],
                "text": obs["text"],
                "issues": issues,
                "critique": s.get("critique", ""),
            })

    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "obs_count": len(observations),
        "judged_count": sum(1 for s in scores.values() if s.get("sample_count", 0) > 0),
        "avg_specificity": _avg(specs),
        "avg_tag_fit": _avg(tags),
        "avg_uniqueness": _avg(uniqs),
        "avg_signal_strength": _avg(sigs),
        "problem_count": len(problems),
        "problems": problems,
    }


def render_report(summaries: List[Dict[str, Any]]) -> str:
    lines: List[str] = ["# Insight Lattice L1 judge report", ""]
    lines.append(f"_Generated at {time.strftime('%Y-%m-%d %H:%M:%S')}._")
    lines.append("")
    lines.append("## Scores per scenario (median across N judge samples)")
    lines.append("")
    lines.append("| scenario | obs | spec ↑ | tag_fit ↑ | uniq ↑ | signal ↑ | problems |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for s in summaries:
        lines.append(
            f"| {s['scenario']} | {s['obs_count']} | "
            f"{s.get('avg_specificity','–')} | "
            f"{s.get('avg_tag_fit','–')} | "
            f"{s.get('avg_uniqueness','–')} | "
            f"{s.get('avg_signal_strength','–')} | "
            f"{s['problem_count']} |"
        )

    lines.append("")
    lines.append("## Observations flagged as problems")
    lines.append("")
    any_problems = False
    for s in summaries:
        if not s["problems"]:
            continue
        any_problems = True
        lines.append(f"### {s['scenario']}")
        for p in s["problems"]:
            lines.append(f"- **{p['kind']}** — {p['text'][:100]}")
            lines.append(f"  - issues: {', '.join(p['issues'])}")
            if p["critique"]:
                lines.append(f"  - critique: _{p['critique']}_")
    if not any_problems:
        lines.append("_No observations flagged as low-quality._")
    return "\n".join(lines)


def run(n_samples: int, scenario_names: Optional[List[str]] = None,
        report_path: Optional[Path] = None) -> Dict[str, Any]:
    if scenario_names:
        selected = [s for s in SCENARIOS if s.name in scenario_names]
        if not selected:
            raise SystemExit(f"No scenarios match {scenario_names}")
    else:
        selected = SCENARIOS

    summaries: List[Dict[str, Any]] = []
    all_scores: Dict[str, Dict[str, Any]] = {}

    for sc in selected:
        print(f"\n=== Scenario: {sc.name} ===")
        print(f"  seeding …")
        seed_scenario(sc)
        print(f"  fetching L1 …")
        obs = fetch_observations()
        print(f"  {len(obs)} observations generated")
        print(f"  judging ({n_samples}× self-consistency) …")
        scores = judge_observations(obs, n_samples=n_samples)
        s = summarize_run(sc, obs, scores)
        summaries.append(s)
        all_scores[sc.name] = {
            "scenario": asdict(sc),
            "observations": obs,
            "scores": scores,
            "summary": s,
        }
        print(f"  spec={s.get('avg_specificity')} tag_fit={s.get('avg_tag_fit')} "
              f"uniq={s.get('avg_uniqueness')} signal={s.get('avg_signal_strength')} · "
              f"{s['problem_count']} flagged")

    report = render_report(summaries)
    print("\n" + report)

    if report_path:
        report_path.write_text(report, encoding="utf-8")
        json_path = report_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {"generated_at": time.time(), "runs": all_scores, "summaries": summaries},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nReport written to: {report_path}")
        print(f"JSON written to:   {json_path}")

    # Cleanup so we don't leave test data
    reset_project()

    return {"runs": all_scores, "summaries": summaries, "report": report}


def _backend_up() -> bool:
    try:
        with urllib.request.urlopen(BASE_URL + "api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=3, help="self-consistency samples")
    parser.add_argument("--scenarios", nargs="+", default=None,
                        help="subset of scenario names (default: all)")
    parser.add_argument("--report", type=Path, default=None,
                        help="write markdown report to this path")
    args = parser.parse_args()

    if not _backend_up():
        print(f"Backend not reachable at {BASE_URL}", file=sys.stderr)
        sys.exit(2)

    result = run(n_samples=args.n, scenario_names=args.scenarios,
                 report_path=args.report)
    # Exit non-zero if any scenario scored noise >= 3.5 on average
    for s in result["summaries"]:
        if (s.get("avg_noise") or 0) >= 3.5:
            print(f"\nWARN: {s['scenario']} noise score above threshold", file=sys.stderr)


if __name__ == "__main__":
    main()
