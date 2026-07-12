"""Portfolio cross-structure ("chokepoint") engine — bidirectional.

The per-stock drawer answers "what is THIS company". This answers what
metrics can't: **across my whole book, who do my holdings SHARE?**

Edges per holding:
  · suppliers / customers / competitors  ← SEC-anchored facts (10-K, verbatim-gated)
  · institutional owners                 ← 13F signal_events (whale moves, with Δ)

BIDIRECTIONAL (#1): every extracted edge is also an edge for the counterparty,
so sparse per-company data compounds into a denser graph — BUT the relation
**flips** on reversal and that flip is correctness-critical:
    competitor(A→B)  ⟹  competitor(B→A)      [symmetric]
    supplier(A→B="B supplies A")  ⟹  customer(B→A="A is B's customer")
    customer(A→B="B buys from A") ⟹  supplier(B→A="A supplies B")
A reverse edge is a pure LOGICAL INVERSION of a verbatim-gated fact — nothing
is invented; it carries the SAME source (filing, fact_id, quote, date) so it
stays 100% traceable. Reverse edges are only created when the entity resolves
to a real ticker (no phantom nodes from fuzzy names).

Everything DB-sourced (anchored_facts + signal_events) — no yfinance, so it is
throttle-immune. Every edge carries provenance + the source filing date
(freshness); stale filings (>18mo) are flagged.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from agent.finance.persistence import connect, ensure_schema
from agent.finance.positions import list_lots

# relation inversion on reversal — the correctness-critical map
_INV = {"competitor": "competitor", "supplier": "customer", "customer": "supplier"}
_STALE_DAYS = 550  # ~18 months — a 10-K older than this is flagged stale

_STOP = re.compile(
    r"\b(inc|corp|corporation|ltd|limited|llc|plc|company|co|holdings|"
    r"technology|technologies|group|the|systems|semiconductor|"
    r"manufacturing|international|industries)\b"
)


def _norm(name: Optional[str], ticker: Optional[str]) -> str:
    if ticker and ticker.strip():
        return ticker.upper().strip()
    n = re.sub(r"[,.&]", " ", (name or "").lower())
    n = _STOP.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()[:28]


def _stale(filing_date: Optional[str]) -> Optional[bool]:
    if not filing_date:
        return None
    try:
        d = datetime.fromisoformat(filing_date[:10]).date()
        return (date.today() - d).days > _STALE_DAYS
    except Exception:
        return None


def _build_value_chain_edges(conn) -> List[dict]:
    """All competitor/supplier/customer edges (direct + reverse) with full
    provenance. Reverse edges flip the relation and only exist when the entity
    resolves to a ticker."""
    rows = conn.execute(
        "SELECT id, ticker, fact_type, payload_json, evidence_quote, "
        "       source_filing_date, source_accession, source_url "
        "FROM stock_anchored_facts "
        "WHERE fact_type IN ('competitor','supplier','customer')"
    ).fetchall()
    edges: List[dict] = []
    for r in rows:
        p = json.loads(r["payload_json"]) if r["payload_json"] else {}
        ent_tk = (p.get("ticker") or "").upper().strip() or None
        ent_key = _norm(p.get("name"), ent_tk)
        if not ent_key:
            continue
        prov = {
            "source_ticker":  r["ticker"],
            "fact_id":        r["id"],
            "quote":          (r["evidence_quote"] or "")[:300],
            "filing_date":    r["source_filing_date"],
            "accession":      r["source_accession"],
            "source_url":     r["source_url"],
            "weight":         p.get("concentration_pct"),
            "stale":          _stale(r["source_filing_date"]),
        }
        # direct: src --fact_type--> entity
        edges.append({
            "frm": r["ticker"].upper(), "rel": r["fact_type"],
            "to_key": ent_key, "to_disp": ent_tk or p.get("name"),
            "to_ticker": ent_tk, "kind": "direct", "prov": prov,
        })
        # reverse: entity --INV(fact_type)--> src  (only if entity has a ticker)
        if ent_tk:
            edges.append({
                "frm": ent_tk, "rel": _INV[r["fact_type"]],
                "to_key": r["ticker"].upper(), "to_disp": r["ticker"],
                "to_ticker": r["ticker"].upper(), "kind": "reverse", "prov": prov,
            })
    return edges


def compute_crossstructure(owner_lookback_days: int = 400) -> Dict[str, Any]:
    ensure_schema()
    held = sorted({(l.get("symbol") or "").upper() for l in list_lots(open_only=True) if l.get("symbol")})
    held_set = set(held)
    if not held:
        return {"held": [], "n_held": 0, "shared": {}, "internal": [], "coverage": {}, "freshness": {}}

    with connect() as conn:
        all_edges = _build_value_chain_edges(conn)
        # owners from 13F whale moves
        ph = ",".join("?" * len(held))
        owner_rows = conn.execute(
            f"SELECT ticker, body_json, source_url, source_timestamp, detected_at FROM signal_events "
            f"WHERE scanner_name='13f' AND ticker IN ({ph}) "
            f"  AND date(detected_at) >= date('now', ?)",
            (*held, f"-{owner_lookback_days} days"),
        ).fetchall()

    # value-chain: keep edges originating from a HELD ticker
    held_edges = [e for e in all_edges if e["frm"] in held_set]

    # group by (rel, entity) → which holdings touch it (+ provenance per holding)
    grouped: Dict[str, Dict[str, dict]] = defaultdict(dict)  # f"{rel}|{key}" -> {holding -> edge}
    disp: Dict[str, str] = {}
    for e in held_edges:
        gk = f"{e['rel']}|{e['to_key']}"
        # prefer a direct edge over reverse if both exist for same holding
        cur = grouped[gk].get(e["frm"])
        if cur is None or (cur["kind"] == "reverse" and e["kind"] == "direct"):
            grouped[gk][e["frm"]] = e
        disp[gk] = e["to_disp"]

    def shared_for(ft: str) -> List[dict]:
        out = []
        for gk, by_holding in grouped.items():
            rel, _ = gk.split("|", 1)
            if rel != ft or len(by_holding) < 2:
                continue
            ent_disp = disp[gk]
            edges_out = {}
            for h, e in sorted(by_holding.items()):
                edges_out[h] = {
                    "kind":        e["kind"],          # direct | reverse(derived)
                    "weight":      e["prov"]["weight"],
                    "via":         e["prov"]["source_ticker"],
                    "fact_id":     e["prov"]["fact_id"],
                    "quote":       e["prov"]["quote"],
                    "filing_date": e["prov"]["filing_date"],
                    "source_url":  e["prov"]["source_url"],
                    "stale":       e["prov"]["stale"],
                }
            out.append({
                "entity": ent_disp,
                "entity_ticker": next((e["to_ticker"] for e in by_holding.values() if e["to_ticker"]), None),
                "is_held": (ent_disp or "").upper() in held_set,
                "n": len(by_holding),
                "holdings": sorted(by_holding.keys()),
                "edges": edges_out,
            })
        out.sort(key=lambda x: (-x["n"], x["entity"]))
        return out

    # owners (13F) — institution shared across holdings, with direction + date
    own: Dict[str, Dict[str, dict]] = defaultdict(dict)
    own_disp: Dict[str, str] = {}
    own_meta: Dict[str, dict] = {}   # whale_key + source_url for hyperlinking
    for r in owner_rows:
        b = json.loads(r["body_json"]) if r["body_json"] else {}
        whale = (b.get("whale") or "").strip()
        if not whale:
            continue
        key = whale.lower()
        own[key][r["ticker"].upper()] = {
            "dir": b.get("change_type"), "weight": b.get("whale_signal_weight"),
            "filing_date": b.get("filing_date") or (r["source_timestamp"] or "")[:10],
        }
        own_disp[key] = whale
        if key not in own_meta:
            own_meta[key] = {"whale_key": b.get("whale_key"), "source_url": r["source_url"]}
    owner_shared = []
    for key, by_h in own.items():
        if len(by_h) >= 2:
            owner_shared.append({
                "entity": own_disp[key], "entity_ticker": None, "is_held": False,
                "whale_key": own_meta.get(key, {}).get("whale_key"),
                "source_url": own_meta.get(key, {}).get("source_url"),
                "n": len(by_h), "holdings": sorted(by_h.keys()), "edges": by_h,
            })
    owner_shared.sort(key=lambda x: (-x["n"], x["entity"]))

    shared = {
        "supplier": shared_for("supplier"),
        "customer": shared_for("customer"),
        "competitor": shared_for("competitor"),
        "owner": owner_shared,
    }

    # coverage per held ticker (now counting direct + reverse-gained edges)
    coverage = {t: {"competitor": 0, "supplier": 0, "customer": 0, "owner": 0} for t in held}
    seen_cov = set()
    for e in held_edges:
        sig = (e["frm"], e["rel"], e["to_key"])
        if sig in seen_cov:
            continue
        seen_cov.add(sig)
        coverage[e["frm"]][e["rel"]] = coverage[e["frm"]].get(e["rel"], 0) + 1
    for key, by_h in own.items():
        for h in by_h:
            coverage[h]["owner"] = coverage[h].get("owner", 0) + 1

    # internal links: a held ticker is competitor/supplier/customer of another held
    seen, internal = set(), []
    for e in held_edges:
        if e["frm"] in held_set and e["rel"] != "owner":
            tgt = (e["to_ticker"] or "").upper()
            if tgt in held_set and tgt != e["frm"]:
                sig = (e["frm"], e["rel"], tgt)
                if sig not in seen:
                    seen.add(sig)
                    internal.append({"from": e["frm"], "rel": e["rel"], "to": tgt,
                                     "kind": e["kind"], "via": e["prov"]["source_ticker"]})

    # freshness summary: oldest/newest value-chain filing in use + stale count
    dates = [e["prov"]["filing_date"] for e in held_edges if e["prov"]["filing_date"]]
    n_stale = sum(1 for e in held_edges if e["prov"]["stale"])
    freshness = {
        "value_chain_oldest_filing": min(dates) if dates else None,
        "value_chain_newest_filing": max(dates) if dates else None,
        "n_edges": len(held_edges),
        "n_reverse": sum(1 for e in held_edges if e["kind"] == "reverse"),
        "n_stale_edges": n_stale,
        "owner_source": "13F (quarterly, ~45d lag)",
    }

    return {
        "held": held, "n_held": len(held),
        "shared": shared, "internal": internal,
        "coverage": coverage, "freshness": freshness,
    }


def build_crossstructure_router() -> APIRouter:
    router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    @router.get("/crossstructure")
    def crossstructure() -> Dict[str, Any]:
        """Portfolio-level shared edges (chokepoints / correlation), bidirectional,
        DB-sourced, every edge provenance- + freshness-stamped."""
        return compute_crossstructure()

    return router
