"""NeoMind Knowledge Graph — A-Mem Zettelkasten Implementation

Transforms NeoMind's flat learning list into an interconnected knowledge
graph inspired by the Zettelkasten method and A-Mem (NeurIPS 2025).

Key concepts:
- Each learning becomes a "note" in the Zettelkasten
- Notes connect via typed edges (causes, contradicts, supports, extends, etc.)
- Associative retrieval: given a query, traverse the graph to find related knowledge
- Emergent structure: clusters and themes arise from connection patterns

Unlike traditional vector-only memory, this captures *relationships* between
pieces of knowledge, enabling chain-of-thought reasoning across learnings.

Example: "Fed raises rates" → (causes) → "Growth stocks decline"
                             → (contradicts) → "Market rallies on strong earnings"
                             → (supports) → "Dollar strengthens"

Research: A-Mem (NeurIPS 2025, arxiv 2502.12110)
No external dependencies — stdlib only.
"""

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("/data/neomind/db/learnings.db")

# Edge types for knowledge connections
EDGE_TYPES = {
    "causes":       "A causes or leads to B",
    "caused_by":    "A is caused by B (inverse of causes)",
    "supports":     "A provides evidence for B",
    "contradicts":  "A contradicts or conflicts with B",
    "extends":      "A adds detail or nuance to B",
    "similar_to":   "A and B are about the same topic",
    "prerequisite": "A must be understood before B",
    "applied_in":   "A was applied in the context of B",
}

# How many hops to traverse for associative retrieval
MAX_TRAVERSAL_DEPTH = 3

# Minimum edge weight to consider during traversal
MIN_EDGE_WEIGHT = 0.3


class KnowledgeGraph:
    """Zettelkasten-style knowledge graph built on top of LearningsEngine.

    The graph is stored in SQLite alongside the learnings data.
    Edges have types, weights, and optional context.

    Usage:
        kg = KnowledgeGraph()

        # Add connections (can be done manually or by LLM)
        kg.add_edge(learning_id_1, learning_id_2, "causes", weight=0.9)

        # Associative retrieval: find related knowledge
        related = kg.get_associated(learning_id, depth=2)

        # Get reasoning chain between two learnings
        chain = kg.find_path(from_id, to_id)

        # Discover clusters (emergent themes)
        clusters = kg.discover_clusters()
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS knowledge_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            edge_type TEXT NOT NULL,
            weight REAL DEFAULT 0.5,
            context TEXT,
            created_at TEXT NOT NULL,
            last_traversed_at TEXT,
            traversal_count INTEGER DEFAULT 0,
            FOREIGN KEY (source_id) REFERENCES learnings(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES learnings(id) ON DELETE CASCADE,
            UNIQUE(source_id, target_id, edge_type)
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_type ON knowledge_edges(edge_type);

        CREATE TABLE IF NOT EXISTS knowledge_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            learning_ids TEXT NOT NULL,    -- JSON array
            centroid_id INTEGER,           -- Most connected learning in cluster
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """

    def __init__(self, db_path: Optional[Path] = None):
        if isinstance(db_path, str):
            db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.db_path = db_path or DB_PATH
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            # Ensure learnings table exists (may be standalone DB without learnings.py)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT,
                    created_at TEXT
                )
            """)
            conn.executescript(self.SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init knowledge graph DB: {e}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── Edge Management ─────────────────────────────────

    def add_edge(self, source_id: int, target_id: int,
                 edge_type: str, weight: float = 0.5,
                 context: Optional[str] = None) -> bool:
        """Add a directed edge between two learnings.

        Args:
            source_id: Source learning ID
            target_id: Target learning ID
            edge_type: One of EDGE_TYPES keys
            weight: Edge strength (0.0-1.0)
            context: Optional context for this connection

        Returns:
            True if edge was added
        """
        if edge_type not in EDGE_TYPES:
            logger.warning(f"Unknown edge type: {edge_type}")
            return False

        if source_id == target_id:
            return False

        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._conn()
            conn.execute(
                """INSERT OR REPLACE INTO knowledge_edges
                   (source_id, target_id, edge_type, weight, context, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source_id, target_id, edge_type,
                 max(0.0, min(1.0, weight)), context, now)
            )
            conn.commit()
            conn.close()
            logger.debug(f"Edge added: {source_id} --[{edge_type}]--> {target_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to add edge: {e}")
            return False

    def add_bidirectional(self, id_a: int, id_b: int,
                          edge_type: str, weight: float = 0.5,
                          context: Optional[str] = None) -> bool:
        """Add edges in both directions (for symmetric relationships like 'similar_to')."""
        ok1 = self.add_edge(id_a, id_b, edge_type, weight, context)
        ok2 = self.add_edge(id_b, id_a, edge_type, weight, context)
        return ok1 and ok2

    def remove_edge(self, source_id: int, target_id: int,
                    edge_type: Optional[str] = None) -> int:
        """Remove edge(s) between two learnings.

        Returns: number of edges removed
        """
        try:
            conn = self._conn()
            if edge_type:
                result = conn.execute(
                    "DELETE FROM knowledge_edges WHERE source_id=? AND target_id=? AND edge_type=?",
                    (source_id, target_id, edge_type)
                )
            else:
                result = conn.execute(
                    "DELETE FROM knowledge_edges WHERE source_id=? AND target_id=?",
                    (source_id, target_id)
                )
            deleted = result.rowcount
            conn.commit()
            conn.close()
            return deleted
        except Exception:
            return 0

    def get_edges(self, learning_id: int,
                  direction: str = "both") -> List[Dict]:
        """Get all edges connected to a learning.

        Args:
            learning_id: The learning to query
            direction: "outgoing", "incoming", or "both"

        Returns:
            List of edge dicts with source_id, target_id, edge_type, weight
        """
        try:
            conn = self._conn()
            edges = []

            if direction in ("outgoing", "both"):
                rows = conn.execute(
                    "SELECT * FROM knowledge_edges WHERE source_id=?",
                    (learning_id,)
                ).fetchall()
                edges.extend(dict(r) for r in rows)

            if direction in ("incoming", "both"):
                rows = conn.execute(
                    "SELECT * FROM knowledge_edges WHERE target_id=?",
                    (learning_id,)
                ).fetchall()
                edges.extend(dict(r) for r in rows)

            conn.close()
            return edges
        except Exception:
            return []

    # ── Associative Retrieval ──────────────────────────

    def get_associated(self, learning_id: int,
                       depth: int = 2,
                       min_weight: float = MIN_EDGE_WEIGHT,
                       max_results: int = 20) -> List[Dict]:
        """Traverse the knowledge graph to find associated learnings.

        BFS traversal from the starting learning, following edges
        up to `depth` hops, weighted by edge strength and hop distance.

        Args:
            learning_id: Starting learning ID
            depth: Max traversal depth (hops)
            min_weight: Minimum edge weight to traverse
            max_results: Max learnings to return

        Returns:
            List of dicts with learning_id, relevance_score, path
        """
        if depth > MAX_TRAVERSAL_DEPTH:
            depth = MAX_TRAVERSAL_DEPTH

        visited: Dict[int, float] = {}  # learning_id → best relevance score
        paths: Dict[int, List] = {}     # learning_id → path taken
        queue: List[Tuple[int, float, List, int]] = [(learning_id, 1.0, [], 0)]

        try:
            conn = self._conn()

            while queue:
                current_id, current_score, current_path, current_depth = queue.pop(0)

                if current_depth > depth:
                    continue

                if current_id in visited and visited[current_id] >= current_score:
                    continue

                visited[current_id] = current_score
                paths[current_id] = current_path

                if current_depth >= depth:
                    continue

                # Get outgoing edges
                rows = conn.execute(
                    "SELECT target_id, edge_type, weight FROM knowledge_edges "
                    "WHERE source_id=? AND weight >= ?",
                    (current_id, min_weight)
                ).fetchall()

                for row in rows:
                    target = row["target_id"]
                    edge_weight = row["weight"]
                    # Score decays with each hop
                    new_score = current_score * edge_weight * 0.7
                    new_path = current_path + [{
                        "from": current_id,
                        "to": target,
                        "type": row["edge_type"],
                        "weight": edge_weight,
                    }]

                    if target not in visited or visited[target] < new_score:
                        queue.append((target, new_score, new_path, current_depth + 1))

                # Also record traversal for analytics
                conn.execute(
                    """UPDATE knowledge_edges
                       SET traversal_count = traversal_count + 1,
                           last_traversed_at = ?
                       WHERE source_id = ?""",
                    (datetime.now(timezone.utc).isoformat(), current_id)
                )

            conn.commit()
            conn.close()

            # Remove the starting node from results
            visited.pop(learning_id, None)

            # Sort by relevance score
            results = [
                {
                    "learning_id": lid,
                    "relevance": round(score, 4),
                    "path": paths.get(lid, []),
                    "hops": len(paths.get(lid, [])),
                }
                for lid, score in visited.items()
            ]
            results.sort(key=lambda x: x["relevance"], reverse=True)
            return results[:max_results]

        except Exception as e:
            logger.error(f"Associative retrieval failed: {e}")
            return []

    def find_path(self, from_id: int, to_id: int,
                  max_depth: int = 5) -> Optional[List[Dict]]:
        """Find the shortest path between two learnings in the graph.

        Uses BFS. Returns the path as a list of edge dicts, or None if no path.
        """
        if from_id == to_id:
            return []

        try:
            conn = self._conn()
            visited = {from_id}
            queue = [(from_id, [])]

            for _ in range(max_depth):
                next_queue = []
                for current_id, path in queue:
                    rows = conn.execute(
                        "SELECT target_id, edge_type, weight FROM knowledge_edges WHERE source_id=?",
                        (current_id,)
                    ).fetchall()

                    for row in rows:
                        target = row["target_id"]
                        new_path = path + [{
                            "from": current_id,
                            "to": target,
                            "type": row["edge_type"],
                            "weight": row["weight"],
                        }]

                        if target == to_id:
                            conn.close()
                            return new_path

                        if target not in visited:
                            visited.add(target)
                            next_queue.append((target, new_path))

                queue = next_queue
                if not queue:
                    break

            conn.close()
            return None  # No path found
        except Exception as e:
            logger.error(f"Path finding failed: {e}")
            return None

    # ── Cluster Discovery ──────────────────────────────

    def discover_clusters(self, min_cluster_size: int = 3) -> List[Dict]:
        """Discover emergent knowledge clusters using connected components.

        Uses a simple connected-components algorithm to find groups
        of heavily interconnected learnings.

        Returns:
            List of cluster dicts with name, learning_ids, size, centroid
        """
        try:
            conn = self._conn()
            edges = conn.execute(
                "SELECT source_id, target_id FROM knowledge_edges WHERE weight >= ?",
                (MIN_EDGE_WEIGHT,)
            ).fetchall()
            conn.close()

            if not edges:
                return []

            # Build adjacency list (undirected)
            adj: Dict[int, Set[int]] = defaultdict(set)
            for e in edges:
                adj[e["source_id"]].add(e["target_id"])
                adj[e["target_id"]].add(e["source_id"])

            # Find connected components
            visited: Set[int] = set()
            clusters = []

            for node in adj:
                if node in visited:
                    continue

                # BFS to find component
                component = set()
                queue = [node]
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    visited.add(current)
                    component.add(current)
                    for neighbor in adj[current]:
                        if neighbor not in visited:
                            queue.append(neighbor)

                if len(component) >= min_cluster_size:
                    # Find centroid (most connected node)
                    centroid = max(component, key=lambda n: len(adj[n] & component))

                    clusters.append({
                        "learning_ids": sorted(component),
                        "size": len(component),
                        "centroid_id": centroid,
                        "density": self._cluster_density(component, adj),
                    })

            clusters.sort(key=lambda c: c["size"], reverse=True)
            return clusters

        except Exception as e:
            logger.error(f"Cluster discovery failed: {e}")
            return []

    @staticmethod
    def _cluster_density(nodes: Set[int], adj: Dict[int, Set[int]]) -> float:
        """Calculate edge density of a cluster (0-1)."""
        n = len(nodes)
        if n < 2:
            return 0
        max_edges = n * (n - 1)  # Directed graph
        actual_edges = sum(
            len(adj[node] & nodes)
            for node in nodes
        )
        return round(actual_edges / max_edges, 3)

    # ── LLM-Assisted Connection ────────────────────────

    def suggest_connections_prompt(self, learning_id: int,
                                    candidates: List[Dict]) -> str:
        """Generate prompt for LLM to suggest connections between learnings.

        Args:
            learning_id: The focal learning
            candidates: List of potential connection targets (from get_relevant)

        Returns:
            Prompt string for LLM
        """
        try:
            conn = self._conn()
            focal = conn.execute(
                "SELECT * FROM learnings WHERE id=?", (learning_id,)
            ).fetchone()
            conn.close()

            if not focal:
                return ""

            candidates_text = "\n".join(
                f"  ID {c['id']}: [{c['type']}] {c['content'][:100]}"
                for c in candidates[:10]
            )

            edge_types_text = "\n".join(
                f"  {k}: {v}" for k, v in EDGE_TYPES.items()
            )

            return f"""Analyze the relationships between these learnings.

Focal learning (ID {focal['id']}):
  [{focal['type']}] {focal['content']}

Candidate learnings:
{candidates_text}

Available relationship types:
{edge_types_text}

For each meaningful connection, output a JSON array:
[
  {{"source": {focal['id']}, "target": <candidate_id>, "type": "<edge_type>", "weight": 0.1-1.0, "reason": "brief explanation"}}
]

Rules:
- Only suggest connections that represent genuine knowledge relationships
- Weight reflects strength of the relationship (0.1=weak, 1.0=definitive)
- A learning can have multiple connections of different types
- Return empty array [] if no meaningful connections exist

JSON output only:"""
        except Exception:
            return ""

    def ingest_llm_connections(self, llm_output: str) -> int:
        """Parse LLM-suggested connections and add to graph.

        Returns: number of edges added
        """
        count = 0
        try:
            text = llm_output.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("\n", 1)[0]

            items = json.loads(text)
            if not isinstance(items, list):
                return 0

            for item in items:
                if all(k in item for k in ("source", "target", "type")):
                    ok = self.add_edge(
                        source_id=item["source"],
                        target_id=item["target"],
                        edge_type=item["type"],
                        weight=item.get("weight", 0.5),
                        context=item.get("reason"),
                    )
                    if ok:
                        count += 1
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Failed to parse LLM connections: {e}")
        return count

    # ── Statistics & Analytics ─────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        try:
            conn = self._conn()
            total_edges = conn.execute(
                "SELECT COUNT(*) FROM knowledge_edges"
            ).fetchone()[0]

            by_type = {}
            for row in conn.execute(
                "SELECT edge_type, COUNT(*) as c FROM knowledge_edges GROUP BY edge_type"
            ):
                by_type[row["edge_type"]] = row["c"]

            # Number of learnings with at least one edge
            connected = conn.execute(
                """SELECT COUNT(DISTINCT id) FROM (
                    SELECT source_id as id FROM knowledge_edges
                    UNION
                    SELECT target_id as id FROM knowledge_edges
                )"""
            ).fetchone()[0]

            total_learnings = conn.execute(
                "SELECT COUNT(*) FROM learnings"
            ).fetchone()[0]

            # Most connected learning
            top_connected = conn.execute(
                """SELECT source_id, COUNT(*) as c FROM knowledge_edges
                   GROUP BY source_id ORDER BY c DESC LIMIT 5"""
            ).fetchall()

            avg_weight = conn.execute(
                "SELECT AVG(weight) FROM knowledge_edges"
            ).fetchone()[0] or 0

            conn.close()

            return {
                "total_edges": total_edges,
                "edges_by_type": by_type,
                "connected_learnings": connected,
                "total_learnings": total_learnings,
                "graph_coverage": round(connected / max(1, total_learnings), 3),
                "avg_edge_weight": round(avg_weight, 3),
                "top_connected": [
                    {"learning_id": r["source_id"], "edges": r["c"]}
                    for r in top_connected
                ],
            }
        except Exception:
            return {"total_edges": 0}

    def get_neighborhood(self, learning_id: int) -> Dict[str, Any]:
        """Get a learning's immediate neighborhood (1-hop context).

        Useful for enriching prompts with related knowledge.
        """
        edges = self.get_edges(learning_id)

        causes = [e for e in edges if e.get("edge_type") == "causes" and e.get("source_id") == learning_id]
        caused_by = [e for e in edges if e.get("edge_type") == "caused_by" and e.get("source_id") == learning_id]
        supports = [e for e in edges if e.get("edge_type") == "supports"]
        contradicts = [e for e in edges if e.get("edge_type") == "contradicts"]
        similar = [e for e in edges if e.get("edge_type") == "similar_to"]

        return {
            "learning_id": learning_id,
            "total_connections": len(edges),
            "causes": len(causes),
            "caused_by": len(caused_by),
            "supports": len(supports),
            "contradicts": len(contradicts),
            "similar": len(similar),
            "edges": edges[:20],  # Cap for prompt injection
        }


# ── Singleton ──────────────────────────────────────

_kg: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    """Get or create the global KnowledgeGraph singleton."""
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg
