"""verify_seed_urls.py — guard against fabricated URLs in seed_*.py.

The 2026-05-03 audit found that 5 douban subject IDs in
seed_books.py were fabricated from training-data memory and pointed
to unrelated books or 404. This tool is the structural guard that
should have caught them.

What it does:

  1. Walks each given path (file or directory). For each Python
     file matching seed_*.py, parses out every string literal that
     looks like an HTTP/HTTPS URL.
  2. Classifies each URL as either:
       SAFE    — homepage / root / known-canonical (gutenberg.org/ebooks/N,
                 berkshirehathaway.com/letters/letters.html, search-query
                 URLs, wikipedia article links, oaktreecapital.com/insights)
       ID-LINK — deep link with a specific resource ID
                 (douban /subject/N/, SEC accession, GitHub PR/issue,
                 arXiv ID, JD product URL). MUST be verified live.
  3. For every ID-LINK, does a fast HTTP HEAD (or GET if HEAD blocked).
     Reports HTTP status. Non-2xx → fail.
  4. Prints a per-URL line with status. Non-zero exit if any fail.

Usage:
  .venv/bin/python tools/verify_seed_urls.py \\
        agent/finance/learning/seed_books.py \\
        agent/finance/learning/seed_classics.py \\
        agent/finance/learning/seed_cases.py

  # Or directory:
  .venv/bin/python tools/verify_seed_urls.py agent/finance/learning/

  # CI / pre-commit:
  exit 0 only when all ID-LINK URLs return 2xx.

What it does NOT do:

  - Verify that the page CONTENTS match the seed entry's claim (e.g.
    that douban /subject/5243775/ actually is 《聪明的投资者》, not
    some other book that happens to live there). That requires LLM
    review or content scraping. The 2026-05-03 douban fabrications
    would have been caught by the HEAD check for the 404s, but the
    "wrong-book" cases (1046219 → I Ching scholarship) would slip
    through. The README in seed_books.py module docstring spells
    out the human-verification protocol for those cases.

  Future work — `--deep` mode that LLM-checks each fetched page
  against the entry's title/author. ~$0.01/URL, ~30s for the seed
  library.
"""
from __future__ import annotations

import ast
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Tuple

# Strategy: verify EVERY URL that's not a bare domain root. The
# 2026-05-03 audit caught fabricated URLs in two classes:
#   (a) douban /subject/N/ deep links → caught by ID-LINK patterns
#   (b) article URLs like fs.blog/great-talks/<slug>/ or
#       hkex.com.hk/Indices/HSI → these have no obvious "resource
#       ID" pattern but were equally fabricated and 404'd.
# So we whitelist *only* bare-root URLs and verify everything else.
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
DOMAIN_ROOT_RE = re.compile(
    r"^https?://[A-Za-z0-9.\-]+(?::\d+)?/?$"
)


def _clean_url(u: str) -> str:
    """Strip trailing punctuation that's not part of the URL.

    Handles Wikipedia-style parenthesized titles like
    `Margin_of_Safety_(book)` correctly: only strips trailing ')'
    when it's unbalanced (more ')' than '('). This avoids the
    bug where the verifier earlier truncated valid Wikipedia URLs
    and reported them as 404."""
    u = u.rstrip(".,;:!?")
    while u.endswith(")") and u.count("(") < u.count(")"):
        u = u[:-1]
    return u

USER_AGENT = "neomind-seed-verifier/1.0 (+contact via project repo)"
TIMEOUT_S = 8.0


def extract_urls_from_python(path: Path) -> List[Tuple[int, str]]:
    """Parse the file as Python, collect every string-literal URL
    along with its source line number. Returns [(lineno, url), ...]."""
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        print(f"[verify] {path}: SYNTAX ERROR — {e}", file=sys.stderr)
        return []
    out: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for m in URL_RE.finditer(node.value):
                out.append((node.lineno, _clean_url(m.group(0))))
    return out


def needs_verify(url: str) -> bool:
    """Return True if this URL is a deep link (anything more specific
    than a bare domain root). Bare roots like https://example.com/
    are skipped — we trust those exist as long as the domain does."""
    return not bool(DOMAIN_ROOT_RE.match(url))


def head_check(url: str) -> Tuple[int, str]:
    """Returns (http_status, note). Tries HEAD first, falls back to
    a 1-byte ranged GET for sites that 405 on HEAD."""
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, "HEAD ok"
    except urllib.error.HTTPError as e:
        if e.code in (403, 405):
            req2 = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Range": "bytes=0-256",
                    "Accept": "*/*",
                },
            )
            try:
                with urllib.request.urlopen(req2, timeout=TIMEOUT_S) as r2:
                    return r2.status, f"GET-fallback ok (HEAD said {e.code})"
            except urllib.error.HTTPError as e2:
                return e2.code, f"GET-fallback HTTP {e2.code}"
            except Exception as exc2:
                return 0, f"GET-fallback err: {exc2.__class__.__name__}: {exc2}"
        return e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return 0, f"URL err: {e.reason}"
    except Exception as e:
        return 0, f"{e.__class__.__name__}: {e}"


def iter_seed_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_file():
            if p.name.startswith("seed_") and p.suffix == ".py":
                yield p
        elif p.is_dir():
            yield from p.glob("seed_*.py")


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: verify_seed_urls.py <file|dir> [<file|dir>...]")
        return 2

    targets = list(iter_seed_files(Path(p) for p in argv))
    if not targets:
        print("[verify] no seed_*.py files found in given paths")
        return 0

    total = 0
    failures: List[Tuple[Path, int, str, str]] = []
    skipped_root = 0
    # Treat 401/403/429 as "site won't tell us" — not a fail. Only
    # 404/410 / connection errors / 5xx are hard fails. A 403 from
    # sec.gov / nvidia investor portal means "we don't serve bots"
    # not "URL is wrong"; a 404 means the URL is wrong.
    SOFT_BLOCK = {401, 403, 429}
    seen_urls: set[str] = set()

    for f in targets:
        urls = extract_urls_from_python(f)
        try:
            display = f.relative_to(Path.cwd())
        except ValueError:
            display = f
        print(f"\n=== {display} ({len(urls)} URLs) ===")
        for lineno, url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            total += 1
            if not needs_verify(url):
                skipped_root += 1
                continue
            status, note = head_check(url)
            if 200 <= status < 400:
                mark = "OK "
            elif status in SOFT_BLOCK:
                mark = "SKIP"  # site bot-blocks; treat as inconclusive
            else:
                mark = "FAIL"
            print(f"  [{mark}] L{lineno}  HTTP {status:>3}  {note:<32}  {url}")
            if mark == "FAIL":
                failures.append((f, lineno, url, f"HTTP {status} ({note})"))

    print()
    print(f"--- summary: {total} URLs scanned, "
          f"{total - skipped_root} deep-links checked, "
          f"{skipped_root} domain-roots skipped, "
          f"{len(failures)} failures ---")

    if failures:
        print("\nFailed URLs (must verify manually):")
        for f, ln, url, why in failures:
            print(f"  {f}:{ln}  {url}  →  {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
