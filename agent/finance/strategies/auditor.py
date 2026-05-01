"""Layer 0 — strategies auditor.

Promotes ``provenance.state: unverified`` entries in
``docs/strategies/strategies.yaml`` to ``verified`` (or
``partially_verified``) by:

1.  WebFetching a curated set of authoritative sources for the
    strategy's topic.
2.  Storing each fetched body as a content-addressed RawStore blob
    (sha256 verifiable).
3.  Asking an LLM, with the corpus bytes as context, whether a
    specific claim is supported — the LLM must cite a verbatim
    phrase.
4.  Mechanical post-validation: the cited phrase must literally
    appear in the cited blob's bytes, AND any specific number in
    the claim must appear in the cited phrase.  This is the
    anti-hallucination teeth: an LLM can lie about what it saw,
    but it cannot make grep find a string that isn't there.

The auditor is a Python tool callable from the scheduler / CLI /
HTTP endpoint.  Per design, **the LLM is reduced to an extractor**;
it never generates a fact, only confirms or denies that a candidate
fact appears in given bytes.

Run modes:
* ``audit_strategy(id)``                — audit one entry
* ``audit_all(limit)``                  — audit N oldest unverified
* CLI: ``python -m agent.finance.strategies.auditor --id <id>``
* CLI: ``python -m agent.finance.strategies.auditor --all --limit 5``
* Scheduler job: ``audit_strategies`` (Layer 0a)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


# ── Curated source whitelist ─────────────────────────────────────
#
# DO NOT let the LLM choose which URLs to fetch.  An LLM choosing
# URLs is the same hallucination class as an LLM writing URLs.
# Instead, we hand-pick a small set of authoritative sources by
# topic, fetched with stable URL patterns.

_SOURCE_URLS: Dict[str, List[str]] = {
    # Wikipedia is the canonical "we know this URL works" choice:
    # stable URLs, machine-readable HTML, plenty of cited numeric
    # claims, and on every educational topic it's the highest-quality
    # plain-text source on the open web.  We picked Wikipedia
    # specifically AFTER the original "curated whitelist" of
    # cboe.com / optionseducation.org / etc. failed with HTTP 404
    # on 2026-04-27 — those URLs were author-hallucinated from
    # training rather than personally verified.  Lesson exemplified
    # the very bug the auditor exists to catch.
    "options_general": [
        "https://en.wikipedia.org/wiki/Option_(finance)",
        "https://en.wikipedia.org/wiki/Covered_call",
        "https://en.wikipedia.org/wiki/Iron_condor",
    ],
    "etf_general": [
        "https://en.wikipedia.org/wiki/Exchange-traded_fund",
        "https://en.wikipedia.org/wiki/Index_fund",
    ],
    "tax_general": [
        "https://en.wikipedia.org/wiki/Wash_sale",
        "https://en.wikipedia.org/wiki/Capital_gains_tax_in_the_United_States",
    ],
    "pdt_rules": [
        "https://en.wikipedia.org/wiki/Pattern_day_trader",
    ],
}


def _topic_for_strategy(entry: Dict[str, Any]) -> List[str]:
    """Pick which curated source bundles apply to a strategy.
    Conservative — better to under-fetch than over-fetch."""
    topics: List[str] = []
    asset = entry.get("asset_class", "")
    horizon = entry.get("horizon", "")
    if asset == "options":
        topics.append("options_general")
    if asset == "etf":
        topics.append("etf_general")
    if entry.get("pdt_relevant") or horizon in ("intraday", "days"):
        topics.append("pdt_rules")
    if entry.get("tax_treatment", {}).get("section_1256"):
        topics.append("tax_general")
    return topics or ["options_general"]


# ── Numeric claim extraction ─────────────────────────────────────


# Detect specific numeric claims in free text — "~70-80%", "55%",
# "$10k", "1.5x".  These are the things the LLM hallucinates and
# the user can't tell from typography.
_NUM_PATTERNS = [
    re.compile(r"~?\d+(?:\.\d+)?%"),                        # "70%" / "~70%"
    re.compile(r"~?\d+(?:\.\d+)?-\d+(?:\.\d+)?%"),           # "70-80%"
    re.compile(r"\$\d+(?:\.\d+)?[kKmM]?"),                  # "$10k"
    re.compile(r"\d+(?:\.\d+)?x"),                          # "1.5x"
]


def _extract_numeric_claims(text: str) -> List[str]:
    """All numeric tokens in ``text``.  Used to decide which fields
    need verification + as the literal-substring check the auditor
    enforces."""
    out: List[str] = []
    for pat in _NUM_PATTERNS:
        for m in pat.findall(text):
            if m not in out:
                out.append(m)
    return out


# ── Audit result types ──────────────────────────────────────────


@dataclass
class ClaimVerdict:
    """One claim's audit outcome."""
    field:        str           # "typical_win_rate" / "max_loss" / etc.
    claim_text:   str           # original field text
    numbers:      List[str]     # numeric tokens detected
    state:        str           # "supported" / "unsupported" / "qualitative"
    cited_blob:   Optional[str] = None      # raw://<sha256> if supported
    cited_phrase: Optional[str] = None      # verbatim phrase from blob
    rejection_reason: Optional[str] = None  # if mechanical check failed


@dataclass
class AuditReport:
    strategy_id: str
    started_at:  str
    finished_at: str
    corpus:      List[str]                  # raw://<sha256> list
    verdicts:    List[ClaimVerdict] = field(default_factory=list)
    overall_state: str = "unverified"
    error:       Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id":   self.strategy_id,
            "started_at":    self.started_at,
            "finished_at":   self.finished_at,
            "corpus":        self.corpus,
            "verdicts":      [
                {k: v for k, v in vd.__dict__.items() if v is not None}
                for vd in self.verdicts
            ],
            "overall_state": self.overall_state,
            "error":         self.error,
        }


# ── Corpus building (WebFetch → RawStore) ───────────────────────


def _fetch_into_rawstore(url: str, project_id: str) -> Optional[str]:
    """Fetch ``url`` synchronously; on success, write the body bytes
    to RawStore via ``add_blob``; return ``raw://<sha256>``.  Returns
    None on failure (network error, 4xx/5xx).

    Uses httpx (already a project dep) instead of stdlib urllib —
    urllib on macOS Python often fails opaquely on TLS without a
    certifi bundle; httpx ships its own cert chain and behaves
    consistently across hosts.  Also follows redirects (some
    publishers like investor.gov return 301 → /www/...).
    """
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={
                # A real-looking user-agent — bot-detection on bigger
                # publisher sites blocks plain "library/version" UAs.
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36 NeoMind-auditor/1.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("auditor: %s httpx error %s, skip", url, exc)
        return None
    except Exception as exc:
        logger.warning("auditor: %s fetch failed %r, skip", url, exc)
        return None

    if resp.status_code != 200:
        logger.info("auditor: %s returned %d, skip", url, resp.status_code)
        return None
    body = resp.content

    try:
        from agent.finance.raw_store import RawStore
    except Exception as exc:
        logger.warning("auditor: RawStore unavailable: %s", exc)
        return None

    store = RawStore.for_project(project_id)
    with store.open_crawl_run(
        source="strategies_auditor",
        query={"url": url},
    ) as crawl:
        meta = crawl.add_blob(
            body,
            url=url,
            response_status=200,
            response_headers={"X-Source": "auditor"},
            valid_time=None,
        )
    return f"raw://{meta.sha256}"


def _read_blob_text(raw_uri: str, project_id: str) -> str:
    """Resolve raw://<sha256> back to a UTF-8 string.  Best-effort
    decode; if the bytes aren't valid UTF-8, replace errors so the
    LLM gets something usable."""
    sha = raw_uri.replace("raw://", "")
    from agent.finance.raw_store import RawStore
    from agent.finance.raw_store.blobs import read_blob_bytes
    store = RawStore.for_project(project_id)
    body = read_blob_bytes(store.raw_root, sha)
    return body.decode("utf-8", errors="replace")


# ── LLM extractor (LLM as extractor, not generator) ─────────────


def _build_audit_prompt(claim_text: str, claim_numbers: List[str], corpus_chunks: List[Tuple[str, str]]) -> str:
    """Construct a strict extraction prompt.

    Key wording choices:
    * 'verbatim' / 'character-for-character' — anchor LLM to literal
      phrasing
    * 'reply with EITHER ... OR ...' — bound the response space
    * 'do not paraphrase, do not summarise' — block restatement
    """
    corpus_lines = "\n\n".join(
        f"[CORPUS_BLOB {i+1}: {raw_uri}]\n{text}"
        for i, (raw_uri, text) in enumerate(corpus_chunks)
    )
    nums_block = ", ".join(claim_numbers) or "(no specific numbers in claim)"
    return (
        "You are a citation extractor — NOT a fact generator.  Your job is\n"
        "to determine whether a CANDIDATE CLAIM is literally supported by\n"
        "any phrase in the supplied CORPUS.  The corpus is the ONLY\n"
        "ground truth; ignore anything you 'know' from training.\n"
        "\n"
        "CANDIDATE CLAIM (verbatim):\n"
        f"  {claim_text}\n"
        "\n"
        f"NUMERIC TOKENS IN CLAIM: {nums_block}\n"
        "\n"
        "RULES:\n"
        "  1. To answer 'supported', you must paste a phrase from the\n"
        "     corpus character-for-character (verbatim, exact spelling,\n"
        "     exact punctuation).  No paraphrasing.\n"
        "  2. The cited phrase must contain at least one of the numeric\n"
        "     tokens listed above (if any).\n"
        "  3. If you cannot find a verbatim phrase that contains the\n"
        "     numeric tokens AND backs the claim's meaning, answer\n"
        "     'unsupported'.\n"
        "  4. Do not invent.  If unsure, answer 'unsupported'.\n"
        "\n"
        "CORPUS:\n"
        f"{corpus_lines}\n"
        "\n"
        "Reply ONLY with JSON, exactly this shape:\n"
        "{\n"
        '  "verdict":      "supported" | "unsupported",\n'
        '  "cited_blob":   "raw://<sha256>"  (or null if unsupported),\n'
        '  "cited_phrase": "verbatim phrase from corpus" (or null),\n'
        '  "reasoning":    "one short sentence"\n'
        "}\n"
    )


def _call_llm_audit(prompt: str) -> Dict[str, Any]:
    """Call DeepSeek with a JSON-only response.  Returns the parsed
    JSON or a fallback ``unsupported`` verdict on any error.

    We deliberately reuse the model + endpoint pattern from
    ``research_brief.py`` so this auditor doesn't introduce a new
    LLM provider surface.
    """
    import httpx

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"verdict": "unsupported", "cited_blob": None, "cited_phrase": None,
                "reasoning": "no DEEPSEEK_API_KEY in env"}

    try:
        resp = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content":
                        "You are a citation extractor.  You never invent facts.  "
                        "You only confirm whether a phrase exists in the corpus "
                        "verbatim.  Reply with JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,           # deterministic — auditor needs no creativity
                "response_format": {"type": "json_object"},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:
        logger.warning("auditor LLM call failed: %s", exc)
        return {"verdict": "unsupported", "cited_blob": None, "cited_phrase": None,
                "reasoning": f"llm error: {exc}"}


# ── Mechanical post-validation (the anti-hallucination teeth) ───


def _mechanical_validate(
    cited_phrase: Optional[str],
    cited_blob:   Optional[str],
    corpus_text_by_uri: Dict[str, str],
    claim_numbers: List[str],
) -> Tuple[bool, Optional[str]]:
    """Return ``(passes, reject_reason)``.

    The LLM cannot cheat past this: we literally substring-search.
    """
    if not cited_phrase or not cited_blob:
        return False, "LLM did not provide a citation"
    blob_text = corpus_text_by_uri.get(cited_blob)
    if blob_text is None:
        return False, f"LLM cited unknown blob {cited_blob}"
    # The cited phrase must literally appear in the blob bytes.
    # Normalise whitespace for both sides — HTML scraping introduces
    # extra spaces/newlines that don't change meaning but trip
    # naive substring match.
    norm_blob   = re.sub(r"\s+", " ", blob_text).strip()
    norm_phrase = re.sub(r"\s+", " ", cited_phrase).strip()
    if not norm_phrase or norm_phrase not in norm_blob:
        return False, ("LLM cited a phrase not literally in corpus "
                       "(probable hallucination)")
    # If the claim contains specific numbers, at least one of them
    # must appear in the cited phrase.  This catches the case where
    # the LLM picks a real-but-unrelated phrase.
    if claim_numbers:
        nums_in_phrase = [n for n in claim_numbers
                          if re.sub(r"\s+", "", n).strip("~") in re.sub(r"\s+", "", norm_phrase).strip("~")]
        if not nums_in_phrase:
            return False, ("LLM citation does not contain any of the "
                           "claim's numeric tokens")
    return True, None


# ── Top-level audit_strategy ─────────────────────────────────────


_PROJECT_ID = "fin-core"

_AUDITED_FIELDS = (
    "max_loss",
    "typical_win_rate",
    "feasible_at_10k_reason",
    "starter_step",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def audit_strategy(strategy_id: str, *, project_id: str = _PROJECT_ID) -> AuditReport:
    """Audit one strategy entry by id.

    Returns an :class:`AuditReport` regardless of outcome — even on
    fetch failures we return a report with ``error=...`` and
    ``overall_state='unverified'`` so callers can persist it.
    """
    started = _utcnow_iso()

    # Load yaml + locate entry
    from agent.finance.strategies_catalog import _STRATEGIES_YAML
    raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    entries = raw.get("strategies", []) or []
    entry = next((s for s in entries if s.get("id") == strategy_id), None)
    if entry is None:
        return AuditReport(
            strategy_id=strategy_id,
            started_at=started,
            finished_at=_utcnow_iso(),
            corpus=[],
            error=f"strategy id {strategy_id!r} not found in {_STRATEGIES_YAML}",
        )

    # Build corpus — fetch each curated source for this topic
    topics = _topic_for_strategy(entry)
    urls: List[str] = []
    for t in topics:
        urls.extend(_SOURCE_URLS.get(t, []))

    corpus_uris: List[str] = []
    corpus_text: Dict[str, str] = {}
    for url in urls:
        uri = _fetch_into_rawstore(url, project_id)
        if uri is None:
            continue
        corpus_uris.append(uri)
        try:
            corpus_text[uri] = _read_blob_text(uri, project_id)
        except Exception as exc:
            logger.warning("auditor: read_blob failed for %s: %s", uri, exc)

    if not corpus_uris:
        # Surface WHY each URL failed so the user can debug instead of
        # staring at "no corpus blobs could be fetched".  We replay
        # the fetch loop, this time capturing the exception text per URL.
        per_url_errors: List[str] = []
        for u in urls:
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(15.0),
                    follow_redirects=True,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/121.0.0.0 Safari/537.36 NeoMind-auditor/1.0"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                    },
                ) as client:
                    r = client.get(u)
                    per_url_errors.append(f"{u} -> HTTP {r.status_code} ({len(r.content)} bytes)")
            except Exception as exc:
                per_url_errors.append(f"{u} -> {type(exc).__name__}: {exc}")
        return AuditReport(
            strategy_id=strategy_id,
            started_at=started,
            finished_at=_utcnow_iso(),
            corpus=[],
            error="no corpus blobs could be fetched: " + " | ".join(per_url_errors),
        )

    # Audit each verifiable field
    verdicts: List[ClaimVerdict] = []
    for fname in _AUDITED_FIELDS:
        text = entry.get(fname)
        if not isinstance(text, str) or not text.strip():
            continue
        nums = _extract_numeric_claims(text)
        if not nums:
            # Qualitative-only field passes by definition
            verdicts.append(ClaimVerdict(
                field=fname, claim_text=text, numbers=[],
                state="qualitative",
            ))
            continue

        prompt = _build_audit_prompt(
            claim_text=text,
            claim_numbers=nums,
            corpus_chunks=[(uri, corpus_text[uri][:6000]) for uri in corpus_uris],
        )
        reply = _call_llm_audit(prompt)
        passes, reason = _mechanical_validate(
            cited_phrase=reply.get("cited_phrase"),
            cited_blob=  reply.get("cited_blob"),
            corpus_text_by_uri=corpus_text,
            claim_numbers=nums,
        )
        if reply.get("verdict") == "supported" and passes:
            verdicts.append(ClaimVerdict(
                field=fname, claim_text=text, numbers=nums,
                state="supported",
                cited_blob=reply.get("cited_blob"),
                cited_phrase=reply.get("cited_phrase"),
            ))
        else:
            # LLM said unsupported, OR LLM said supported but mechanical
            # check rejected.  Both → unsupported.
            verdicts.append(ClaimVerdict(
                field=fname, claim_text=text, numbers=nums,
                state="unsupported",
                rejection_reason=reason or reply.get("reasoning") or "LLM verdict: unsupported",
            ))

    # Roll-up state
    n_supported     = sum(1 for v in verdicts if v.state == "supported")
    n_unsupported   = sum(1 for v in verdicts if v.state == "unsupported")
    n_qualitative   = sum(1 for v in verdicts if v.state == "qualitative")
    n_total         = n_supported + n_unsupported + n_qualitative
    if n_total == 0 or (n_supported == 0 and n_unsupported > 0):
        overall = "unverified"
    elif n_unsupported == 0:
        overall = "verified" if n_supported > 0 else "qualitative"
    else:
        overall = "partially_verified"

    return AuditReport(
        strategy_id=strategy_id,
        started_at=started,
        finished_at=_utcnow_iso(),
        corpus=corpus_uris,
        verdicts=verdicts,
        overall_state=overall,
    )


# ── Persistence: write report into yaml + audit log ─────────────


def write_audit_back(report: AuditReport) -> None:
    """Persist the audit verdict into ``docs/strategies/strategies.yaml``.

    Only updates ``provenance``; never touches the strategy's actual
    free-text content.  If a claim was supported, the cited blob
    raw:// is added to ``sources``.  Audit log retained as a sibling
    JSON file for full forensics.
    """
    from agent.finance.strategies_catalog import _STRATEGIES_YAML, _STRATEGIES_DIR
    raw = yaml.safe_load(_STRATEGIES_YAML.read_text(encoding="utf-8")) or {}
    strategies = raw.get("strategies", []) or []
    target = next((s for s in strategies if s.get("id") == report.strategy_id), None)
    if target is None:
        logger.warning("write_audit_back: strategy %s not found", report.strategy_id)
        return

    # Update provenance
    prov = target.setdefault("provenance", {})
    prov["state"]  = "qualitative" if report.overall_state == "qualitative" else report.overall_state
    prov["source"] = (
        f"Layer 0 auditor {report.finished_at} "
        f"(corpus={len(report.corpus)} blobs)"
    )

    # Add raw://<sha256> citations for any supported claim
    new_sources = list(target.get("sources") or [])
    for v in report.verdicts:
        if v.state == "supported" and v.cited_blob and v.cited_blob not in new_sources:
            new_sources.append(v.cited_blob)
    target["sources"] = new_sources

    # Write yaml back, preserving the header comment
    text = _STRATEGIES_YAML.read_text(encoding="utf-8")
    header_end = text.find("strategies:")
    header = text[:header_end] if header_end >= 0 else ""
    body = yaml.safe_dump({"strategies": strategies},
                         sort_keys=False, allow_unicode=True,
                         default_flow_style=False, width=120)
    _STRATEGIES_YAML.write_text(header + body, encoding="utf-8")

    # Write the full report alongside for forensics
    log_dir = _STRATEGIES_DIR / "audit_logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{report.strategy_id}_{report.finished_at.replace(':','-')}.json"
    log_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    logger.info("write_audit_back: %s → %s, log at %s",
                report.strategy_id, prov["state"], log_path)


def audit_all(*, limit: int = 5, project_id: str = _PROJECT_ID) -> List[AuditReport]:
    """Audit the next ``limit`` unverified entries.  Returns the list
    of reports for caller to log / display."""
    from agent.finance.strategies_catalog import _load_catalog
    items = _load_catalog()
    unverified = [s for s in items if s.get("provenance", {}).get("state") == "unverified"]
    out: List[AuditReport] = []
    for entry in unverified[:limit]:
        rep = audit_strategy(entry["id"], project_id=project_id)
        write_audit_back(rep)
        out.append(rep)
    return out


# ── CLI entry ────────────────────────────────────────────────────


def _cli() -> int:
    p = argparse.ArgumentParser(description="Strategies catalog auditor (Layer 0)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", help="audit a single strategy by id")
    g.add_argument("--all", action="store_true", help="audit N oldest unverified")
    p.add_argument("--limit", type=int, default=5,
                   help="--all batch size (default 5)")
    p.add_argument("--project-id", default=_PROJECT_ID)
    p.add_argument("--dry-run", action="store_true",
                   help="run audit but do NOT write back to yaml")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    reports: List[AuditReport]
    if args.id:
        reports = [audit_strategy(args.id, project_id=args.project_id)]
    else:
        # Avoid auto-write inside audit_all when --dry-run: re-implement
        # the loop here.
        from agent.finance.strategies_catalog import _load_catalog
        items = _load_catalog()
        unverified = [s for s in items if s.get("provenance", {}).get("state") == "unverified"]
        reports = [audit_strategy(e["id"], project_id=args.project_id) for e in unverified[:args.limit]]

    for r in reports:
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        if not args.dry_run:
            write_audit_back(r)

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
