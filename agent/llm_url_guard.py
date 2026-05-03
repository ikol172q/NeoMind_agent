"""System-wide URL hallucination guard for LLM outputs.

WHY THIS EXISTS
---------------
LLMs routinely fabricate URLs. They invent plausible-looking paths
(sec.gov/Archives/.../some-slug, reuters.com/business/some-slug,
bloomberg.com/news/articles/...) that 404 because the model "remembers"
the site format but not the specific URL. ~70% of LLM-emitted URLs
fail when HEAD-checked.

NeoMind's contract with the user: we never display a URL we have not
HEAD-verified at least once. This module is the single chokepoint
that enforces that.

USAGE
-----
For free-text replies (chat, summaries, insights):
    from agent.llm_url_guard import sanitize_text
    text, stats = sanitize_text(llm_reply, context_hint="NVDA earnings")
    # stats = {'n_total', 'n_verified', 'n_dead', 'dead_urls': [...]}

For structured citation lists (stock_research profile etc):
    from agent.llm_url_guard import verify_citations
    citations = verify_citations(llm_citations)
    # each cite gets `verified: bool` flag added

For LLM system prompts:
    from agent.llm_url_guard import URL_POLICY_PROMPT
    system_prompt += "\n\n" + URL_POLICY_PROMPT

DESIGN NOTES
------------
- HEAD-check with HEAD→GET fallback (some sites 405 HEAD).
- 7-day TTL cache (url_verification_cache table) so we don't re-check
  the same URL every render.
- Failed URLs are NOT silently dropped — we replace them in text with
  a Google-search markdown link so the user can verify themselves.
  The `[⚠死链:host → Google 搜](query)` marker makes the substitution
  visible (anti-silent-corruption rule).
- URL_POLICY_PROMPT goes into shared system prompt so EVERY LLM call
  knows the policy upstream. Defense-in-depth: prompt discourages
  emission, post-processor catches any that leak through.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ── Shared system prompt snippet ───────────────────────────────

URL_POLICY_PROMPT = """\
URL POLICY (HARD CONSTRAINT — applies to every reply):

You MUST NOT include a URL unless one of these is true:
  (a) the URL appears verbatim in a tool_result message this turn
  (b) the URL appears verbatim in the user's most recent message

For all other source references — even ones you "know" exist —
write the SOURCE TITLE only, no URL. Examples:
  ✓ "Alphabet 2023 Form 10-K (Annual Report)"
  ✓ "Reuters article on DOJ antitrust case, 2024-12"
  ✗ "https://www.sec.gov/Archives/edgar/data/1652044/..."  (fabricated)
  ✗ "https://www.reuters.com/technology/doj-antitrust-..."  (fabricated)

Why: URLs you "remember" from training are wrong ~70% of the time.
sec.gov/Archives/<slug>, reuters.com/business/<slug>, bloomberg.com/<slug>
all 404 frequently because you remember the site shape, not the
specific path. NeoMind's display layer HEAD-checks every URL you
emit and silently downgrades dead links to Google-search fallbacks.
Fabricating URLs does NOT make your reply look more credible — it
gets caught and replaced.

Acceptable domain whitelist (SAFE to cite even without exact path,
because the host itself is reliable as a Google site: search):
  - sec.gov, finance.yahoo.com, www.bloomberg.com, www.wsj.com,
    www.reuters.com, www.cnbc.com — but ONLY if you're certain the
    full URL exists. Otherwise just write the source title.
"""


# ── URL extraction + verification ──────────────────────────────

# Match http(s) URL up to whitespace / quote / bracket / paren.
URL_RE = re.compile(r"https?://[^\s<>\"'\)\]\}]+")


def extract_urls(text: Optional[str]) -> List[str]:
    """Return all http(s) URLs in `text`. Order preserved, dedup."""
    if not text:
        return []
    seen = []
    seen_set = set()
    for m in URL_RE.findall(text):
        # Strip trailing punctuation that's likely not part of URL
        u = m.rstrip(".,;:!?")
        if u in seen_set:
            continue
        seen_set.add(u)
        seen.append(u)
    return seen


def _head_check(url: str, timeout: float = 4.0) -> Tuple[bool, int]:
    """Returns (verified, status_code). status_code = -1 on exception."""
    if not url.startswith(("http://", "https://")):
        return False, 0
    headers = {"User-Agent": "Mozilla/5.0 NeoMind URLGuard"}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=True) as c:
            r = c.head(url, headers=headers)
            if 200 <= r.status_code < 400:
                return True, r.status_code
            # Many sites 405 HEAD or 403 unauth-HEAD; try ranged GET
            if r.status_code in (403, 405):
                r = c.get(url, headers={**headers, "Range": "bytes=0-256"})
                return (200 <= r.status_code < 400), r.status_code
            return False, r.status_code
    except Exception as exc:
        logger.debug("url HEAD failed for %s: %s", url, exc)
        return False, -1


def verify_url(url: str, cache_ttl_days: int = 7) -> bool:
    """HEAD-verify URL. Cached in url_verification_cache table for 7d."""
    if not url:
        return False
    from agent.finance.persistence import connect, ensure_schema
    ensure_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cache_ttl_days)).isoformat()
    try:
        with connect() as conn:
            cur = conn.execute(
                "SELECT verified, checked_at FROM url_verification_cache WHERE url=?",
                (url,),
            )
            row = cur.fetchone()
            if row and row["checked_at"] >= cutoff:
                return bool(row["verified"])
    except Exception as exc:
        logger.warning("url cache lookup failed for %s: %s", url, exc)

    ok, code = _head_check(url)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO url_verification_cache (url, verified, status_code, checked_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET "
                "verified=excluded.verified, "
                "status_code=excluded.status_code, "
                "checked_at=excluded.checked_at",
                (url, 1 if ok else 0, code,
                 datetime.now(timezone.utc).isoformat()),
            )
    except Exception as exc:
        logger.warning("url cache write failed for %s: %s", url, exc)
    return ok


def verify_urls(urls: List[str]) -> Dict[str, bool]:
    """Batch verify URLs in parallel. Returns {url: verified_bool}.

    Uses a small thread pool because each verify_url is a sync HTTP
    HEAD with a 4s timeout — running them sequentially makes a chat
    reply with 5 URLs block 20s. Parallel collapses to ~4s worst case.
    """
    from concurrent.futures import ThreadPoolExecutor
    if not urls:
        return {}
    # Cap thread count — avoid spawning hundreds of threads if an LLM
    # somehow emitted a huge list of URLs.
    max_workers = min(8, len(urls))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(verify_url, urls))
    return dict(zip(urls, results))


# ── Sanitization helpers ───────────────────────────────────────

def _google_search_link(query: str) -> str:
    return f"https://www.google.com/search?q={urllib.parse.quote(query)[:200]}"


def sanitize_text(
    text: str, *, context_hint: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """Replace dead URLs in `text` with markdown links to Google search.

    Returns (sanitized_text, stats):
      stats = {n_total, n_verified, n_dead, dead_urls: [{url, fallback}]}

    Replacement form (markdown):
      [⚠死链:{host} → Google 搜]({google_search_url})

    Verified URLs are left alone — we don't add ✓ markers to text since
    that'd clutter every chat reply. Frontend can show a header notice
    if stats['n_dead'] > 0.
    """
    urls = extract_urls(text)
    if not urls:
        return text, {"n_total": 0, "n_verified": 0, "n_dead": 0, "dead_urls": []}

    # Verify all URLs in parallel — much better worst-case latency
    # than the sequential loop (5 URLs × 4s timeout each = 20s).
    verified_map = verify_urls(urls)

    out = text
    n_verified = 0
    dead_urls: List[Dict[str, str]] = []
    seen: set = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        if verified_map.get(url):
            n_verified += 1
            continue
        host = (urllib.parse.urlparse(url).hostname or url[:30])[:50]
        query = f"{host} {context_hint}".strip()[:120]
        fallback = _google_search_link(query)
        marker = f"[⚠死链:{host} → Google 搜]({fallback})"
        out = out.replace(url, marker, 1)
        dead_urls.append({"url": url, "fallback": fallback, "host": host})

    return out, {
        "n_total":   len(urls),
        "n_verified": n_verified,
        "n_dead":    len(dead_urls),
        "dead_urls": dead_urls,
    }


def verify_citations(citations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For structured citation lists (stock_research profile etc),
    annotate each item with `verified: bool`. Frontend renders
    unverified ones as Google-search fallbacks."""
    if not citations:
        return []
    out = []
    for c in citations:
        if not isinstance(c, dict):
            continue
        url = str(c.get("url") or "").strip()
        c["verified"] = verify_url(url) if url else False
        out.append(c)
    return out
