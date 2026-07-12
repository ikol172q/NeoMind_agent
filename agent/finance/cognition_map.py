"""NeoMind Cognition Map — a personal world-model knowledge graph.

Nodes are plain markdown files under the Investment data-firewall:

    ~/Desktop/Investment/<project_id>/cognition_map/nodes/<id>.md

Design pillars (mirror the user's requirements):

* **md + git is the source of truth** — the vault is its own git repo, so
  every save/delete is a commit and ``git log`` is the change history.
  A SQLite mirror under ``.index/`` is a *rebuildable* cache, never truth.
* **Provenance reuses the anti-hallucination house vocabulary** — a node or
  edge is never "trusted" unless ``provenance.state`` is in
  :data:`TRUSTED_PROVENANCE_STATES`.  Source refs must be ``raw://<sha256>``
  RawStore blobs (actually fetched bytes), never bare training-memory URLs.
  See ``agent/finance/strategies_catalog.py`` and
  ``agent/finance/strategies/auditor.py``.
* **LLM output is never auto-trusted** — anything an LLM proposes is written
  with ``provenance.state = "unverified"`` and ``origin = "llm-expand"`` so it
  lands in the candidate zone until a human (or the auditor) promotes it.

This module is the L0/L1 layer (storage + CRUD + graph query).  It is
deliberately framework-free so it can be unit-tested without the web server;
the FastAPI routers live separately and call into ``CognitionMap``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from agent.finance.investment_projects import get_project_dir
# Reuse the house vocabularies rather than re-declaring them, so the cognition
# map stays in lock-step with the strategies catalog + knowledge graph.
from agent.finance.strategies_catalog import (
    PROVENANCE_STATES,
    TRUSTED_PROVENANCE_STATES,
)
from agent.evolution.knowledge_graph import EDGE_TYPES as _KG_EDGE_TYPES

logger = logging.getLogger(__name__)

# ── Vocabularies ──────────────────────────────────────────────────────

NODE_TYPES = ("concept", "entity", "event", "claim", "source")

# Knowledge-relation edges come straight from the Zettelkasten KG; the three
# facet edges below add the user's "multi-dimensional" axes (req: time / space /
# industry-chain) on top.  "downstream" maps to causes/caused_by, "knowledge"
# maps to prerequisite/extends/similar_to (see LENSES).
EDGE_TYPES: Dict[str, str] = {
    **_KG_EDGE_TYPES,
    "temporal":     "A precedes or follows B in time",
    "spatial":      "A and B share a place / region",
    "supply_chain": "A is upstream/downstream of B in a value chain",
}

# A "lens" is a named projection of the graph onto a subset of edge types,
# so the same data can be viewed as a timeline, a supply chain, a causal web,
# etc. (req: time + space + downstream + industry-chain + knowledge).
LENSES: Dict[str, tuple] = {
    "causal":       ("causes", "caused_by"),
    "time":         ("temporal",),
    "space":        ("spatial",),
    "supply_chain": ("supply_chain",),
    "knowledge":    ("prerequisite", "extends", "similar_to"),
    "evidence":     ("supports", "contradicts"),
}

CONFIDENCE_LEVELS = ("strong", "weak", "doubtful")
ORIGINS = ("manual", "chat", "llm-expand")

# Default-deny: a brand-new or LLM-authored node is unverified until proven.
DEFAULT_PROVENANCE_STATE = "unverified"

# Keep unicode letters/digits (so CJK titles survive); collapse everything
# else to a hyphen.  ``\w`` under re.UNICODE matches CJK, accents, etc.
_SLUG_RE = re.compile(r"[^\w]+", re.UNICODE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def slugify(title: str) -> str:
    """Turn a title into a filesystem-safe, stable, *unicode-preserving* id.

    Deterministic so editing a node with the same title maps back to the same
    file.  Falls back to a content hash when a title has no word characters
    (e.g. all punctuation / emoji), so distinct titles never collide on "node".
    """
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-_")[:80]
    if not slug:
        slug = "node-" + hashlib.md5(title.encode("utf-8")).hexdigest()[:8]
    return slug


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Node (de)serialisation ────────────────────────────────────────────

def serialize_node(node: Dict[str, Any]) -> str:
    """Render a node dict to ``---\\nfrontmatter\\n---\\nbody`` markdown."""
    body = node.pop("body", "") if "body" in node else node.get("_body", "")
    meta = {k: v for k, v in node.items() if k not in ("body", "_body")}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n{body.strip()}\n"


def parse_node(text: str) -> Dict[str, Any]:
    """Parse a markdown node file back into a dict (with ``body`` key)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # Tolerate a body-only file; still return something usable.
        return {"body": text.strip()}
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        meta = {}
    meta["body"] = m.group(2).strip()
    return meta


def normalise_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill defaults + clamp enums.  Default-deny on provenance.

    Mirrors strategies_catalog._normalise_provenance: a node missing
    provenance is treated as 'unverified', never silently trusted.
    """
    n = dict(node)
    title = str(n.get("title") or "").strip()
    n["title"] = title or "(untitled)"
    n["id"] = str(n.get("id") or slugify(n["title"]))

    if n.get("type") not in NODE_TYPES:
        n["type"] = "concept"
    if n.get("confidence") not in CONFIDENCE_LEVELS:
        n["confidence"] = "weak"
    if n.get("origin") not in ORIGINS:
        n["origin"] = "manual"

    prov = n.get("provenance")
    if not isinstance(prov, dict):
        prov = {}
    if prov.get("state") not in PROVENANCE_STATES:
        prov["state"] = DEFAULT_PROVENANCE_STATE
    prov.setdefault("source", "manual entry (unverified default)")
    n["provenance"] = prov

    # sources MUST be raw://<sha256> refs or empty — never bare URLs.
    sources = n.get("sources")
    if not isinstance(sources, list):
        sources = []
    n["sources"] = [s for s in sources if isinstance(s, str) and s.startswith("raw://")]

    edges = n.get("edges")
    if not isinstance(edges, list):
        edges = []
    clean_edges = []
    for e in edges:
        if not isinstance(e, dict) or not e.get("target"):
            continue
        rel = e.get("rel")
        if rel not in EDGE_TYPES:
            continue
        estate = e.get("state")
        if estate not in PROVENANCE_STATES:
            estate = DEFAULT_PROVENANCE_STATE
        clean_edges.append({
            "target": str(e["target"]),
            "rel": rel,
            "weight": max(0.0, min(1.0, float(e.get("weight", 0.5)))),
            "state": estate,
            "note": str(e.get("note") or "") or None,
        })
    n["edges"] = clean_edges

    dims = n.get("dimensions")
    n["dimensions"] = dims if isinstance(dims, dict) else {}

    n.setdefault("created", _today())
    n["last_checked"] = n.get("last_checked") or _today()
    n.setdefault("body", "")
    return n


def is_trusted(node: Dict[str, Any]) -> bool:
    """True iff this node may participate in LLM prompts / decisions.

    Single source of truth, identical gate to strategies_catalog.is_trusted.
    """
    prov = node.get("provenance") or {}
    return prov.get("state") in TRUSTED_PROVENANCE_STATES


# ── The store ─────────────────────────────────────────────────────────

class CognitionMap:
    """File-backed knowledge graph for one investment/cognition project.

    Usage::

        cm = CognitionMap("worldview")
        node = cm.save({"title": "LLM 认知 marginal cost ≈ 0", "type": "claim"})
        cm.link(node["id"], "nvidia-compute-demand", "causes", weight=0.8)
        graph = cm.graph(lens="causal")
    """

    _INDEX_SCHEMA = """
        CREATE TABLE IF NOT EXISTS nodes (
            id           TEXT PRIMARY KEY,
            title        TEXT,
            type         TEXT,
            prov_state   TEXT,
            confidence   TEXT,
            origin       TEXT,
            created      TEXT,
            last_checked TEXT,
            updated_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            rel       TEXT NOT NULL,
            weight    REAL DEFAULT 0.5,
            state     TEXT,
            note      TEXT,
            PRIMARY KEY (source_id, target_id, rel)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_tgt ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel);
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.root = get_project_dir(project_id) / "cognition_map"
        self.nodes_dir = self.root / "nodes"
        self.index_dir = self.root / ".index"
        self.db_path = self.index_dir / "cognition.db"
        self._ensure_vault()

    # ── vault / git lifecycle ─────────────────────────────────────────

    def _ensure_vault(self) -> None:
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git_init()
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            # The index + any embedding cache are derived; only md is truth.
            gitignore.write_text(".index/\n*.faiss\n", encoding="utf-8")
        self._init_index()

    def _git_init(self) -> None:
        try:
            subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
            # Use a synthetic identity so the vault never depends on (or leaks)
            # the user's global git identity, and is clearly app-managed.
            subprocess.run(["git", "config", "user.name", "NeoMind Cognition Map"],
                           cwd=self.root, check=True)
            subprocess.run(["git", "config", "user.email", "cognition-map@neomind.local"],
                           cwd=self.root, check=True)
            logger.info("Initialised cognition-map git vault at %s", self.root)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("git init failed for %s: %s", self.root, e)

    def _git_commit(self, message: str) -> None:
        """Auto-commit the vault.  Local-only; never pushes."""
        try:
            subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
            # Nothing staged → skip (git commit would error on empty).
            staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=self.root)
            if staged.returncode == 0:
                return
            subprocess.run(["git", "commit", "-q", "-m", message], cwd=self.root, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("git commit failed (%s): %s", message, e)

    # ── SQLite index (rebuildable cache) ──────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_index(self) -> None:
        conn = self._conn()
        # WAL so concurrent reads/writes (FastAPI threadpool) don't deadlock
        # on the default rollback journal. Persisted once on the DB file.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(self._INDEX_SCHEMA)
        conn.commit()
        conn.close()

    def _index_node(self, node: Dict[str, Any], conn: sqlite3.Connection) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO nodes
               (id, title, type, prov_state, confidence, origin, created, last_checked, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (node["id"], node["title"], node["type"],
             node["provenance"]["state"], node["confidence"], node["origin"],
             node["created"], node["last_checked"], _now()),
        )
        conn.execute("DELETE FROM edges WHERE source_id=?", (node["id"],))
        for e in node["edges"]:
            conn.execute(
                """INSERT OR REPLACE INTO edges
                   (source_id, target_id, rel, weight, state, note)
                   VALUES (?,?,?,?,?,?)""",
                (node["id"], e["target"], e["rel"], e["weight"], e["state"], e.get("note")),
            )

    def rebuild_index(self) -> int:
        """Rebuild the SQLite cache from the md files (md is truth)."""
        conn = self._conn()
        conn.execute("DELETE FROM nodes")
        conn.execute("DELETE FROM edges")
        count = 0
        for path in self.nodes_dir.glob("*.md"):
            node = normalise_node(parse_node(path.read_text(encoding="utf-8")))
            self._index_node(node, conn)
            count += 1
        conn.commit()
        conn.close()
        return count

    # ── CRUD ──────────────────────────────────────────────────────────

    def _path(self, node_id: str) -> Path:
        return self.nodes_dir / f"{node_id}.md"

    def save(self, node: Dict[str, Any], commit: bool = True) -> Dict[str, Any]:
        node = normalise_node(node)
        self._path(node["id"]).write_text(serialize_node(dict(node)), encoding="utf-8")
        conn = self._conn()
        self._index_node(node, conn)
        conn.commit()
        conn.close()
        if commit:
            self._git_commit(f"save node {node['id']} ({node['provenance']['state']})")
        return node

    def get(self, node_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(node_id)
        if not path.exists():
            return None
        return normalise_node(parse_node(path.read_text(encoding="utf-8")))

    def delete(self, node_id: str, commit: bool = True) -> bool:
        path = self._path(node_id)
        if not path.exists():
            return False
        path.unlink()
        conn = self._conn()
        conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        conn.execute("DELETE FROM edges WHERE source_id=? OR target_id=?", (node_id, node_id))
        conn.commit()
        conn.close()
        # Cascade: other nodes' md files may hold edges pointing TO the deleted
        # node. Strip them so md (source of truth) and the index stay consistent
        # — otherwise a reindex would resurrect dangling edges. git keeps history,
        # so this is recoverable.
        for other_path in self.nodes_dir.glob("*.md"):
            other = normalise_node(parse_node(other_path.read_text(encoding="utf-8")))
            kept = [e for e in other["edges"] if e["target"] != node_id]
            if len(kept) != len(other["edges"]):
                other["edges"] = kept
                self.save(other, commit=False)  # rewrites md + reindexes that node
        if commit:
            self._git_commit(f"delete node {node_id} (+cascade edge cleanup)")
        return True

    def link(self, source_id: str, target_id: str, rel: str,
             weight: float = 0.5, state: str = DEFAULT_PROVENANCE_STATE,
             note: Optional[str] = None) -> bool:
        """Add/replace a typed edge on the source node (and persist)."""
        if source_id == target_id:
            return False
        node = self.get(source_id)
        if node is None or rel not in EDGE_TYPES:
            return False
        node["edges"] = [e for e in node["edges"]
                         if not (e["target"] == target_id and e["rel"] == rel)]
        node["edges"].append({
            "target": target_id, "rel": rel,
            "weight": max(0.0, min(1.0, weight)), "state": state, "note": note,
        })
        self.save(node)
        return True

    # ── queries ───────────────────────────────────────────────────────

    def list_nodes(self, prov_state: Optional[str] = None,
                   trusted_only: bool = False) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM nodes ORDER BY updated_at DESC").fetchall()
        conn.close()
        out = [dict(r) for r in rows]
        if prov_state:
            out = [n for n in out if n["prov_state"] == prov_state]
        if trusted_only:
            out = [n for n in out if n["prov_state"] in TRUSTED_PROVENANCE_STATES]
        return out

    def graph(self, lens: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Return ``{nodes, edges}`` for force-graph rendering.

        ``lens`` restricts edges to one projection (causal/time/space/...).
        """
        rels = LENSES.get(lens) if lens else None
        conn = self._conn()
        nodes = [dict(r) for r in conn.execute("SELECT * FROM nodes").fetchall()]
        if rels:
            placeholders = ",".join("?" * len(rels))
            edges = conn.execute(
                f"SELECT * FROM edges WHERE rel IN ({placeholders})", tuple(rels)
            ).fetchall()
        else:
            edges = conn.execute("SELECT * FROM edges").fetchall()
        conn.close()
        return {"nodes": nodes, "edges": [dict(e) for e in edges]}

    def backup_bundle(self) -> bytes:
        """Return a git bundle of the whole vault — a single file containing
        every node + full history. Restore anywhere with ``git clone x.bundle``.
        Raises if the vault has no commits yet (nothing to back up)."""
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".bundle")
        os.close(fd)
        try:
            subprocess.run(["git", "bundle", "create", tmp, "--all"],
                           cwd=self.root, check=True, capture_output=True)
            with open(tmp, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def history(self, node_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, str]]:
        """Read the git log (req: change history).  Optionally per-node."""
        cmd = ["git", "log", f"-n{limit}", "--pretty=format:%H%x09%aI%x09%s"]
        if node_id:
            cmd += ["--", f"nodes/{node_id}.md"]
        try:
            out = subprocess.run(cmd, cwd=self.root, capture_output=True,
                                 text=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        log = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                log.append({"commit": parts[0], "date": parts[1], "message": parts[2]})
        return log
