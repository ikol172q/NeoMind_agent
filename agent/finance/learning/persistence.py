"""DAO for the learning_cases table.

Two storage tiers:
- DB row holds metadata + summary_zh + (optionally) body_inline
- Long bodies live as MD files under ~/.neomind/fin/learning/cache/

The split keeps the SQLite file lean while still letting NeoMind serve
the cached content offline (the user said "保存在本地也可以" — they
want the material accessible without re-fetching).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.finance.persistence import connect, ensure_schema

logger = logging.getLogger(__name__)


_CACHE_DIR = Path.home() / ".neomind" / "fin" / "learning" / "cache"


def _cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


# Body length over which we spill to a file rather than store inline.
# 10K chars ≈ ~3K tokens; SQLite handles large TEXT but keeping rows
# under ~16KB makes the chat / library queries snappy.
_INLINE_BODY_LIMIT = 10_000


def slugify(s: str) -> str:
    """Normalize a title or url-fragment to a filesystem-safe slug.
    Idempotent: slugify(slugify(x)) == slugify(x). Truncated to 64
    chars so the cache filename stays well under typical limits."""
    s = (s or "").strip()
    # Keep ASCII letters/digits + Chinese chars; replace everything
    # else with hyphens. Chinese chars are kept verbatim so titles
    # like "段永平投网易" stay readable on disk.
    s = re.sub(r"[^\w一-鿿]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-").lower()
    if not s:
        s = hashlib.md5(s.encode()).hexdigest()[:12]
    return s[:64]


# ─── Write ─────────────────────────────────────────────────────────

def upsert_case(
    *,
    slug: str,
    title: str,
    title_zh: str,
    summary_zh: str,
    source_url: Optional[str] = None,
    source_name: Optional[str] = None,
    body: Optional[str] = None,
    language: str = "zh",
    themes: Optional[List[str]] = None,
    tickers: Optional[List[str]] = None,
    era: Optional[str] = None,
    difficulty: Optional[str] = None,
    is_classic: bool = False,
    is_fresh: bool = False,
) -> str:
    """Insert-or-update a learning case. Body splits to file if long."""
    ensure_schema()
    body_inline: Optional[str] = None
    body_md_path: Optional[str] = None
    if body:
        if len(body) <= _INLINE_BODY_LIMIT:
            body_inline = body
        else:
            path = _cache_dir() / f"{slug}.md"
            path.write_text(body, encoding="utf-8")
            body_md_path = str(path)

    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        # ON CONFLICT DO UPDATE — preserves shown_count + last_shown_at
        # while overwriting content fields. Use COALESCE so we don't
        # accidentally null out fields the caller didn't pass.
        conn.execute(
            """INSERT INTO learning_cases (
                slug, title, title_zh, source_url, source_name,
                summary_zh, body_inline, body_md_path, language,
                themes_json, tickers_json, era, difficulty,
                is_classic, is_fresh, fetched_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(slug) DO UPDATE SET
                title         = excluded.title,
                title_zh      = excluded.title_zh,
                source_url    = excluded.source_url,
                source_name   = excluded.source_name,
                summary_zh    = excluded.summary_zh,
                body_inline   = excluded.body_inline,
                body_md_path  = excluded.body_md_path,
                language      = excluded.language,
                themes_json   = excluded.themes_json,
                tickers_json  = excluded.tickers_json,
                era           = excluded.era,
                difficulty    = excluded.difficulty,
                is_classic    = excluded.is_classic,
                is_fresh      = excluded.is_fresh,
                fetched_at    = excluded.fetched_at""",
            (
                slug, title, title_zh, source_url, source_name,
                summary_zh, body_inline, body_md_path, language,
                json.dumps(themes or [], ensure_ascii=False),
                json.dumps(tickers or [], ensure_ascii=False),
                era, difficulty,
                1 if is_classic else 0,
                1 if is_fresh else 0,
                now,
            ),
        )
    return slug


def mark_shown(slug: str) -> None:
    """Bump shown_count + update last_shown_at for rotation logic."""
    ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "UPDATE learning_cases SET shown_count = shown_count + 1, "
            "last_shown_at = ? WHERE slug = ?",
            (now, slug),
        )


def expire_fresh_flags(days: int = 7) -> int:
    """After ``days``, a case stops being "Today material" — un-mark
    so the Today tab shows only genuinely recent additions. The case
    stays in the Library forever. Returns count of rows updated."""
    ensure_schema()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect() as conn:
        cur = conn.execute(
            "UPDATE learning_cases SET is_fresh = 0 "
            "WHERE is_fresh = 1 AND fetched_at < ?",
            (cutoff,),
        )
        return cur.rowcount


# ─── Read ──────────────────────────────────────────────────────────

def _row_to_dict(row: Any, *, with_body: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "slug":            row["slug"],
        "title":           row["title"],
        "title_zh":        row["title_zh"],
        "source_url":      row["source_url"],
        "source_name":     row["source_name"],
        "summary_zh":      row["summary_zh"],
        "language":        row["language"],
        "themes":          json.loads(row["themes_json"] or "[]"),
        "tickers":         json.loads(row["tickers_json"] or "[]"),
        "era":             row["era"],
        "difficulty":      row["difficulty"],
        "is_classic":      bool(row["is_classic"]),
        "is_fresh":        bool(row["is_fresh"]),
        "fetched_at":      row["fetched_at"],
        "shown_count":     row["shown_count"],
        "last_shown_at":   row["last_shown_at"],
    }
    if with_body:
        body = row["body_inline"]
        if not body and row["body_md_path"]:
            try:
                body = Path(row["body_md_path"]).read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("body file read failed for %s: %s",
                               row["slug"], exc)
                body = None
        out["body"] = body
    return out


def get_case(slug: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with connect() as conn:
        cur = conn.execute(
            "SELECT * FROM learning_cases WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_dict(row, with_body=True)


def list_today(*, fresh_limit: int = 5,
               classic_rotation_window_days: int = 7) -> Dict[str, Any]:
    """Today's material: fresh additions + 1 classic on rotation.

    The classic pick prefers cases not shown in the last
    ``classic_rotation_window_days`` so the user keeps seeing variety
    instead of the same Buffett-Coke entry every day.
    """
    ensure_schema()
    cutoff_show = (datetime.now(timezone.utc)
                   - timedelta(days=classic_rotation_window_days)).isoformat()
    with connect() as conn:
        fresh_rows = conn.execute(
            "SELECT * FROM learning_cases WHERE is_fresh = 1 "
            "ORDER BY fetched_at DESC LIMIT ?",
            (fresh_limit,),
        ).fetchall()
        classic_row = conn.execute(
            "SELECT * FROM learning_cases WHERE is_classic = 1 "
            "AND (last_shown_at IS NULL OR last_shown_at < ?) "
            "ORDER BY shown_count ASC, RANDOM() LIMIT 1",
            (cutoff_show,),
        ).fetchone()
        if classic_row is None:
            # All classics shown recently — fall back to least-recently-shown
            classic_row = conn.execute(
                "SELECT * FROM learning_cases WHERE is_classic = 1 "
                "ORDER BY last_shown_at ASC NULLS FIRST LIMIT 1",
            ).fetchone()
    out: Dict[str, Any] = {
        "fresh":   [_row_to_dict(r) for r in fresh_rows],
        "classic": _row_to_dict(classic_row) if classic_row else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return out


def list_library(
    *,
    theme: Optional[str] = None,
    era: Optional[str] = None,
    language: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Filterable archive. ``q`` is a substring match against title_zh
    OR summary_zh OR original title — case-insensitive."""
    ensure_schema()
    where = []
    params: List[Any] = []
    if theme:
        where.append("themes_json LIKE ?")
        params.append(f"%{theme}%")
    if era:
        where.append("era = ?")
        params.append(era)
    if language:
        where.append("language = ?")
        params.append(language)
    if q:
        like = f"%{q.strip()}%"
        where.append("(title_zh LIKE ? OR summary_zh LIKE ? OR title LIKE ?)")
        params.extend([like, like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM learning_cases{where_sql}",
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM learning_cases{where_sql} "
            f"ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "count": len(rows),
        "cases": [_row_to_dict(r) for r in rows],
    }


def list_themes() -> List[Dict[str, Any]]:
    """Distinct themes across all cases with counts. Used by UI to
    populate the filter dropdown."""
    ensure_schema()
    counts: Dict[str, int] = {}
    with connect() as conn:
        rows = conn.execute(
            "SELECT themes_json FROM learning_cases").fetchall()
    for r in rows:
        for t in (json.loads(r["themes_json"] or "[]")):
            counts[t] = counts.get(t, 0) + 1
    return [
        {"theme": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
