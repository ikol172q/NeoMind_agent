#!/usr/bin/env python3
"""LLM-as-judge evaluator for Insight Lattice L1 observations + L2 themes.

Research-backed design (see plans/2026-04-20_insight-lattice.md §A):
- **G-Eval style** rubric-in-prompt with chain-of-thought scoring.
- **Self-consistency N=3**: three judge calls per item at T≈0.3;
  take the median. Research shows this halves judge variance at
  ~3× cost — within budget for ≤40 items per scenario.
- **L1 rubric** (infrastructure-first): specificity / tag_fit /
  uniqueness / signal_strength.
- **L2 rubric** (distillation quality): theme_coherence /
  member_fit / narrative_accuracy / citation_validity.
- **Fixed scenarios** (empty, thin, mid, rich, iv_heavy) so runs
  are comparable over time — drift detection.
- **Output**: structured JSON report + human-readable markdown.
  Flags low-scoring items separately from aggregate stability.

Run:
    .venv/bin/python tools/eval/lattice_judge.py --layer l1
    .venv/bin/python tools/eval/lattice_judge.py --layer l2
    .venv/bin/python tools/eval/lattice_judge.py --layer both
    .venv/bin/python tools/eval/lattice_judge.py --layer l2 --scenarios rich
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

# Bootstrap path so this script can be run standalone (.venv/bin/python tools/eval/lattice_judge.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from agent.constants.models import DEFAULT_MODEL  # noqa: E402

BASE_URL = os.environ.get("NEOMIND_DASHBOARD_URL", "http://127.0.0.1:8001/")
PROJECT = os.environ.get("NEOMIND_PROJECT", "fin-core")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
JUDGE_MODEL = DEFAULT_MODEL


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


def fetch_themes() -> Dict[str, Any]:
    d = _get(f"api/lattice/themes?project_id={PROJECT}&fresh=1", timeout=300)
    return d


def fetch_calls() -> Dict[str, Any]:
    d = _get(f"api/lattice/calls?project_id={PROJECT}&fresh=1", timeout=600)
    return d


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


# ── L2 judge (themes) ──────────────────────────────────

_JUDGE_L2_SYSTEM = (
    "You evaluate L2 themes inside a layered distillation system. "
    "A theme groups L1 observations that share a signature (tag pattern) "
    "and ships a short narrative summarising them. You are judging "
    "whether the theme is a faithful, useful distillation of its "
    "members — not whether the narrative is eloquent. "
    "Respond in JSON only, no prose outside the object."
)

_JUDGE_L2_RUBRIC = """
Score each theme 1-5 on these four axes.

THEME_COHERENCE (do the members belong together?):
  5 = every member clearly fits the theme's intent (e.g. all are
      genuinely earnings-risk plays for theme_earnings_risk)
  3 = most members fit, 1-2 are loose but defensible
  1 = members are a grab-bag; they share a tag but no real narrative

MEMBER_FIT (are the right members chosen for this theme?):
  5 = membership weights track actual relevance — highest-weight
      member IS the most illustrative observation
  3 = weights roughly correct but some ordering is off
  1 = weights seem arbitrary; low-weight member looks more
      important than high-weight one

NARRATIVE_ACCURACY (does the narrative describe what the members show?):
  5 = narrative claim is directly supported by ≥2 members' text/numbers
  3 = narrative supported by one member; others are consistent but
      not cited
  1 = narrative contradicts or ignores members — hallucinated content

CITATION_VALIDITY (are cited numbers traceable to member text?):
  5 = every number in the narrative appears verbatim in at least
      one member's text
  3 = numbers roughly match member text (off by rounding)
  1 = numbers cited that don't appear in any member — hallucination

Notes:
- If a theme is template_fallback (no LLM), judge narrative_accuracy
  and citation_validity as N/A (score 3, no penalty) — template is
  known-safe by construction.
- Empty themes should not be present; if you see one, score all
  axes 1.

For each theme, output:
  {"id": "...", "theme_coherence": N, "member_fit": N,
   "narrative_accuracy": N, "citation_validity": N,
   "critique": "≤25 words on why this score"}
"""


def _judge_l2_prompt(themes: List[Dict[str, Any]], observations: List[Dict[str, Any]]) -> str:
    obs_by_id = {o["id"]: o for o in observations}
    minimal = []
    for t in themes:
        member_view = []
        for m in t.get("members", []):
            o = obs_by_id.get(m["obs_id"])
            if not o:
                continue
            member_view.append({
                "obs_id": m["obs_id"],
                "weight": m["weight"],
                "kind": o["kind"],
                "text": o["text"],
                "tags": o["tags"],
            })
        minimal.append({
            "id": t["id"],
            "title": t["title"],
            "narrative": t["narrative"],
            "narrative_source": t.get("narrative_source"),
            "severity": t["severity"],
            "cited_numbers": t.get("cited_numbers", []),
            "members": member_view,
        })
    return (
        _JUDGE_L2_RUBRIC
        + "\n\nTHEMES TO SCORE:\n"
        + json.dumps(minimal, indent=1)
        + '\n\nReply with {"scores": [ {...}, ... ]}'
    )


def _judge_l2_call(prompt: str, temperature: float = 0.3, timeout: float = 120) -> Dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY missing — run scripts/sync_launchd_env.sh")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            DEEPSEEK_URL,
            json={
                "model": JUDGE_MODEL,
                "messages": [
                    {"role": "system", "content": _JUDGE_L2_SYSTEM},
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


def judge_themes(
    themes: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    n_samples: int = 3,
) -> Dict[str, Dict[str, Any]]:
    if not themes:
        return {}

    axes = ("theme_coherence", "member_fit", "narrative_accuracy", "citation_validity")
    samples: List[List[Dict[str, Any]]] = []
    for i in range(n_samples):
        try:
            reply = _judge_l2_call(_judge_l2_prompt(themes, observations), temperature=0.3)
            scores = reply.get("scores") or []
            if scores:
                samples.append(scores)
        except Exception as exc:
            print(f"  [L2 judge pass {i+1}/{n_samples} FAILED: {exc}]")

    if not samples:
        return {}

    by_id: Dict[str, Dict[str, List[Any]]] = {
        t["id"]: {axis: [] for axis in axes} | {"critique": []}
        for t in themes
    }
    for sample in samples:
        for score in sample:
            tid = score.get("id")
            if tid not in by_id:
                continue
            for axis in axes:
                v = score.get(axis)
                if isinstance(v, (int, float)):
                    by_id[tid][axis].append(float(v))
            if score.get("critique"):
                by_id[tid]["critique"].append(str(score["critique"]))

    aggregate: Dict[str, Dict[str, Any]] = {}
    for tid, bag in by_id.items():
        row: Dict[str, Any] = {}
        for axis in axes:
            vals = bag[axis]
            row[axis] = round(statistics.median(vals), 2) if vals else None
            row[f"{axis}_stdev"] = round(statistics.stdev(vals), 2) if len(vals) >= 2 else 0.0
        row["sample_count"] = len(bag["theme_coherence"])
        row["critique"] = bag["critique"][0] if bag["critique"] else ""
        aggregate[tid] = row
    return aggregate


def summarize_themes_run(
    scenario: Scenario,
    themes: List[Dict[str, Any]],
    scores: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    axes = ("theme_coherence", "member_fit", "narrative_accuracy", "citation_validity")

    def _avg(name: str):
        xs = [s[name] for s in scores.values() if s.get(name) is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    problems: List[Dict[str, Any]] = []
    for t in themes:
        s = scores.get(t["id"], {})
        if not s:
            continue
        issues = []
        for axis in axes:
            v = s.get(axis)
            if v is not None and v <= 2:
                issues.append(f"low {axis} ({v})")
        if issues:
            problems.append({
                "id": t["id"],
                "title": t["title"],
                "narrative": t["narrative"][:120],
                "narrative_source": t.get("narrative_source"),
                "issues": issues,
                "critique": s.get("critique", ""),
            })

    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "theme_count": len(themes),
        "judged_count": sum(1 for s in scores.values() if s.get("sample_count", 0) > 0),
        "avg_theme_coherence": _avg("theme_coherence"),
        "avg_member_fit": _avg("member_fit"),
        "avg_narrative_accuracy": _avg("narrative_accuracy"),
        "avg_citation_validity": _avg("citation_validity"),
        "problem_count": len(problems),
        "problems": problems,
    }


# ── L3 judge (calls) ───────────────────────────────────

_JUDGE_L3_SYSTEM = (
    "You evaluate L3 actionable calls produced by a layered "
    "distillation system. Each call follows the Toulmin model: "
    "claim, grounds (theme_ids), warrant (why grounds imply claim), "
    "qualifier (conditions / confidence), rebuttal (what would "
    "invalidate it). You are judging whether the call is sound as "
    "an argument and useful as guidance — not whether it is "
    "eloquent. Zero calls is an acceptable output when themes don't "
    "support one; if calls are shown, they must meet the bar. "
    "Respond in JSON only, no prose outside the object."
)

_JUDGE_L3_RUBRIC = """
Score each call 1-5 on these five axes.

CLAIM_ACTIONABILITY (is the claim something the user can act on?):
  5 = concrete, verb-first portfolio action with a named target
      (buy/hold/reduce/trim/avoid/hedge/add/wait) AND an object
      (a ticker, sector, or ETF) — a reader could immediately know
      what to change in their book
  3 = directional but vague ("stay cautious", "tilt defensive"),
      no explicit portfolio action
  1 = commentary or advice-to-be-informed, NOT a portfolio
      instruction ("markets are uncertain", "stay informed",
      "watch for volatility", "monitor conditions"). Anything
      where the "action" is just observing or thinking scores 1.

GROUNDS_TRACEABILITY (does the claim follow from the cited grounds?):
  5 = each ground, taken as given, meaningfully supports the claim;
      removing any ground would weaken the case
  3 = grounds are related but one is a stretch
  1 = grounds are cargo-culted — the claim would be identical
      with or without them

WARRANT_VALIDITY (is the warrant a genuine reasoning step?):
  5 = names the mechanism (why the grounds imply the claim), not a
      restatement of either grounds or claim
  3 = plausible but hand-wavy — "because of market conditions"
  1 = tautology / circular / restates the claim

QUALIFIER_SPECIFICITY (does the qualifier tell you when the call
breaks?):
  5 = specific trigger or threshold ("if VIX > 25", "intraday only",
      "for positions ≤ 5% of book")
  3 = gestures at conditionality without naming a threshold
  1 = generic hedge ("market conditions may change")

REBUTTAL_REALISM (is the rebuttal a concrete observable?):
  5 = a specific falsifier the user could actually check
      (e.g. "if earnings come in ≥ 10% below guidance")
  3 = broadly right direction ("if the market trend reverses")
  1 = vague ("unexpected events") or something that never happens

For each call, output:
  {"id": "...", "claim_actionability": N, "grounds_traceability": N,
   "warrant_validity": N, "qualifier_specificity": N,
   "rebuttal_realism": N,
   "critique": "≤25 words on why this score"}
"""


def _judge_l3_prompt(calls: List[Dict[str, Any]], themes: List[Dict[str, Any]]) -> str:
    theme_view = [
        {"id": t["id"], "title": t["title"], "severity": t["severity"],
         "narrative": t["narrative"]}
        for t in themes
    ]
    return (
        _JUDGE_L3_RUBRIC
        + "\n\nCONTEXT — AVAILABLE THEMES (for grounds traceability):\n"
        + json.dumps(theme_view, indent=1)
        + "\n\nCALLS TO SCORE:\n"
        + json.dumps(calls, indent=1)
        + '\n\nReply with {"scores": [ {...}, ... ]}'
    )


def _judge_l3_call(prompt: str, temperature: float = 0.3, timeout: float = 120) -> Dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY missing — run scripts/sync_launchd_env.sh")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            DEEPSEEK_URL,
            json={
                "model": JUDGE_MODEL,
                "messages": [
                    {"role": "system", "content": _JUDGE_L3_SYSTEM},
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


def judge_calls(
    calls: List[Dict[str, Any]],
    themes: List[Dict[str, Any]],
    n_samples: int = 3,
) -> Dict[str, Dict[str, Any]]:
    if not calls:
        return {}

    axes = ("claim_actionability", "grounds_traceability", "warrant_validity",
            "qualifier_specificity", "rebuttal_realism")
    samples: List[List[Dict[str, Any]]] = []
    for i in range(n_samples):
        try:
            reply = _judge_l3_call(_judge_l3_prompt(calls, themes), temperature=0.3)
            scores = reply.get("scores") or []
            if scores:
                samples.append(scores)
        except Exception as exc:
            print(f"  [L3 judge pass {i+1}/{n_samples} FAILED: {exc}]")

    if not samples:
        return {}

    by_id: Dict[str, Dict[str, List[Any]]] = {
        c["id"]: {axis: [] for axis in axes} | {"critique": []}
        for c in calls
    }
    for sample in samples:
        for score in sample:
            cid = score.get("id")
            if cid not in by_id:
                continue
            for axis in axes:
                v = score.get(axis)
                if isinstance(v, (int, float)):
                    by_id[cid][axis].append(float(v))
            if score.get("critique"):
                by_id[cid]["critique"].append(str(score["critique"]))

    aggregate: Dict[str, Dict[str, Any]] = {}
    for cid, bag in by_id.items():
        row: Dict[str, Any] = {}
        for axis in axes:
            vals = bag[axis]
            row[axis] = round(statistics.median(vals), 2) if vals else None
            row[f"{axis}_stdev"] = round(statistics.stdev(vals), 2) if len(vals) >= 2 else 0.0
        row["sample_count"] = len(bag["claim_actionability"])
        row["critique"] = bag["critique"][0] if bag["critique"] else ""
        aggregate[cid] = row
    return aggregate


def summarize_calls_run(
    scenario: Scenario,
    calls: List[Dict[str, Any]],
    scores: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    axes = ("claim_actionability", "grounds_traceability", "warrant_validity",
            "qualifier_specificity", "rebuttal_realism")

    def _avg(name: str):
        xs = [s[name] for s in scores.values() if s.get(name) is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    problems: List[Dict[str, Any]] = []
    for c in calls:
        s = scores.get(c["id"], {})
        if not s:
            continue
        issues = []
        for axis in axes:
            v = s.get(axis)
            if v is not None and v <= 2:
                issues.append(f"low {axis} ({v})")
        if issues:
            problems.append({
                "id": c["id"],
                "claim": c["claim"][:120],
                "grounds": c.get("grounds", []),
                "issues": issues,
                "critique": s.get("critique", ""),
            })

    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "call_count": len(calls),
        "judged_count": sum(1 for s in scores.values() if s.get("sample_count", 0) > 0),
        "avg_claim_actionability": _avg("claim_actionability"),
        "avg_grounds_traceability": _avg("grounds_traceability"),
        "avg_warrant_validity": _avg("warrant_validity"),
        "avg_qualifier_specificity": _avg("qualifier_specificity"),
        "avg_rebuttal_realism": _avg("rebuttal_realism"),
        "problem_count": len(problems),
        "problems": problems,
    }


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


def render_report(
    l1_summaries: List[Dict[str, Any]],
    l2_summaries: List[Dict[str, Any]],
    l3_summaries: List[Dict[str, Any]] = None,
) -> str:
    l3_summaries = l3_summaries or []
    lines: List[str] = ["# Insight Lattice judge report", ""]
    lines.append(f"_Generated at {time.strftime('%Y-%m-%d %H:%M:%S')}._")
    lines.append("")

    if l1_summaries:
        lines.append("## L1 — observations")
        lines.append("")
        lines.append("| scenario | obs | spec ↑ | tag_fit ↑ | uniq ↑ | signal ↑ | problems |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for s in l1_summaries:
            lines.append(
                f"| {s['scenario']} | {s['obs_count']} | "
                f"{s.get('avg_specificity','–')} | "
                f"{s.get('avg_tag_fit','–')} | "
                f"{s.get('avg_uniqueness','–')} | "
                f"{s.get('avg_signal_strength','–')} | "
                f"{s['problem_count']} |"
            )
        lines.append("")
        lines.append("### L1 flagged observations")
        lines.append("")
        any_problems = False
        for s in l1_summaries:
            if not s["problems"]:
                continue
            any_problems = True
            lines.append(f"#### {s['scenario']}")
            for p in s["problems"]:
                lines.append(f"- **{p['kind']}** — {p['text'][:100]}")
                lines.append(f"  - issues: {', '.join(p['issues'])}")
                if p["critique"]:
                    lines.append(f"  - critique: _{p['critique']}_")
        if not any_problems:
            lines.append("_No observations flagged._")
        lines.append("")

    if l2_summaries:
        lines.append("## L2 — themes")
        lines.append("")
        lines.append("| scenario | themes | coherence ↑ | fit ↑ | accuracy ↑ | citation ↑ | problems |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for s in l2_summaries:
            lines.append(
                f"| {s['scenario']} | {s['theme_count']} | "
                f"{s.get('avg_theme_coherence','–')} | "
                f"{s.get('avg_member_fit','–')} | "
                f"{s.get('avg_narrative_accuracy','–')} | "
                f"{s.get('avg_citation_validity','–')} | "
                f"{s['problem_count']} |"
            )
        lines.append("")
        lines.append("### L2 flagged themes")
        lines.append("")
        any_problems = False
        for s in l2_summaries:
            if not s["problems"]:
                continue
            any_problems = True
            lines.append(f"#### {s['scenario']}")
            for p in s["problems"]:
                src = p.get("narrative_source") or "?"
                lines.append(f"- **{p['id']}** ({src}) — {p['narrative']}")
                lines.append(f"  - issues: {', '.join(p['issues'])}")
                if p["critique"]:
                    lines.append(f"  - critique: _{p['critique']}_")
        if not any_problems:
            lines.append("_No themes flagged._")
        lines.append("")

    if l3_summaries:
        lines.append("## L3 — calls")
        lines.append("")
        lines.append("| scenario | calls | action ↑ | grounds ↑ | warrant ↑ | qualifier ↑ | rebuttal ↑ | problems |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for s in l3_summaries:
            lines.append(
                f"| {s['scenario']} | {s['call_count']} | "
                f"{s.get('avg_claim_actionability','–')} | "
                f"{s.get('avg_grounds_traceability','–')} | "
                f"{s.get('avg_warrant_validity','–')} | "
                f"{s.get('avg_qualifier_specificity','–')} | "
                f"{s.get('avg_rebuttal_realism','–')} | "
                f"{s['problem_count']} |"
            )
        lines.append("")
        lines.append("### L3 flagged calls")
        lines.append("")
        any_problems = False
        for s in l3_summaries:
            if not s["problems"]:
                continue
            any_problems = True
            lines.append(f"#### {s['scenario']}")
            for p in s["problems"]:
                lines.append(f"- **{p['id']}** — {p['claim']}")
                lines.append(f"  - grounds: {p['grounds']}")
                lines.append(f"  - issues: {', '.join(p['issues'])}")
                if p["critique"]:
                    lines.append(f"  - critique: _{p['critique']}_")
        if not any_problems:
            lines.append("_No calls flagged._")
    return "\n".join(lines)


def run(n_samples: int, scenario_names: Optional[List[str]] = None,
        report_path: Optional[Path] = None,
        layer: str = "all") -> Dict[str, Any]:
    if scenario_names:
        selected = [s for s in SCENARIOS if s.name in scenario_names]
        if not selected:
            raise SystemExit(f"No scenarios match {scenario_names}")
    else:
        selected = SCENARIOS

    want_l1 = layer in ("l1", "both", "all")
    want_l2 = layer in ("l2", "both", "all")
    want_l3 = layer in ("l3", "all")

    l1_summaries: List[Dict[str, Any]] = []
    l2_summaries: List[Dict[str, Any]] = []
    l3_summaries: List[Dict[str, Any]] = []
    all_scores: Dict[str, Dict[str, Any]] = {}

    for sc in selected:
        print(f"\n=== Scenario: {sc.name} ===")
        print(f"  seeding …")
        seed_scenario(sc)

        bundle: Dict[str, Any] = {"scenario": asdict(sc)}

        obs: List[Dict[str, Any]] = []
        themes: List[Dict[str, Any]] = []

        if want_l1:
            print(f"  fetching L1 …")
            obs = fetch_observations()
            print(f"  {len(obs)} observations generated")
            print(f"  judging L1 ({n_samples}× self-consistency) …")
            l1_scores = judge_observations(obs, n_samples=n_samples)
            s = summarize_run(sc, obs, l1_scores)
            l1_summaries.append(s)
            bundle["observations"] = obs
            bundle["l1_scores"] = l1_scores
            bundle["l1_summary"] = s
            print(f"  L1: spec={s.get('avg_specificity')} tag_fit={s.get('avg_tag_fit')} "
                  f"uniq={s.get('avg_uniqueness')} signal={s.get('avg_signal_strength')} · "
                  f"{s['problem_count']} flagged")

        if want_l2:
            print(f"  fetching L2 …")
            themes_payload = fetch_themes()
            themes = themes_payload.get("themes", [])
            if not obs:
                obs = themes_payload.get("observations", [])
            print(f"  {len(themes)} themes generated")
            print(f"  judging L2 ({n_samples}× self-consistency) …")
            l2_scores = judge_themes(themes, obs, n_samples=n_samples)
            s = summarize_themes_run(sc, themes, l2_scores)
            l2_summaries.append(s)
            bundle["themes"] = themes
            bundle["l2_scores"] = l2_scores
            bundle["l2_summary"] = s
            print(f"  L2: coh={s.get('avg_theme_coherence')} fit={s.get('avg_member_fit')} "
                  f"acc={s.get('avg_narrative_accuracy')} cite={s.get('avg_citation_validity')} · "
                  f"{s['problem_count']} flagged")

        if want_l3:
            print(f"  fetching L3 …")
            calls_payload = fetch_calls()
            calls = calls_payload.get("calls", [])
            if not themes:
                themes = calls_payload.get("themes", [])
            print(f"  {len(calls)} calls generated")
            if calls:
                print(f"  judging L3 ({n_samples}× self-consistency) …")
                l3_scores = judge_calls(calls, themes, n_samples=n_samples)
            else:
                l3_scores = {}
                print(f"  zero calls — skipping judge (0 calls is a valid output)")
            s = summarize_calls_run(sc, calls, l3_scores)
            l3_summaries.append(s)
            bundle["calls"] = calls
            bundle["l3_scores"] = l3_scores
            bundle["l3_summary"] = s
            print(f"  L3: act={s.get('avg_claim_actionability')} grnd={s.get('avg_grounds_traceability')} "
                  f"war={s.get('avg_warrant_validity')} qual={s.get('avg_qualifier_specificity')} "
                  f"reb={s.get('avg_rebuttal_realism')} · {s['problem_count']} flagged")

        all_scores[sc.name] = bundle

    report = render_report(l1_summaries, l2_summaries, l3_summaries)
    print("\n" + report)

    if report_path:
        report_path.write_text(report, encoding="utf-8")
        json_path = report_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(
                {
                    "generated_at": time.time(),
                    "runs": all_scores,
                    "l1_summaries": l1_summaries,
                    "l2_summaries": l2_summaries,
                    "l3_summaries": l3_summaries,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nReport written to: {report_path}")
        print(f"JSON written to:   {json_path}")

    reset_project()

    return {
        "runs": all_scores,
        "l1_summaries": l1_summaries,
        "l2_summaries": l2_summaries,
        "l3_summaries": l3_summaries,
        "report": report,
    }


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
    parser.add_argument("--layer", choices=("l1", "l2", "l3", "both", "all"),
                        default="all",
                        help="which lattice layer to judge ('both' = l1+l2 for backward compat)")
    args = parser.parse_args()

    if not _backend_up():
        print(f"Backend not reachable at {BASE_URL}", file=sys.stderr)
        sys.exit(2)

    run(n_samples=args.n, scenario_names=args.scenarios,
        report_path=args.report, layer=args.layer)


if __name__ == "__main__":
    main()
