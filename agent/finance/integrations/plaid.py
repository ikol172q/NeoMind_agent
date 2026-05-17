"""Plaid Investments integration — pull positions from Schwab / Fidelity / etc.

Uses Plaid's REST API directly (httpx) — no plaid-python SDK
dependency. Tokens are encrypted at rest via Fernet with a key file at
``~/.neomind/fin/secrets/plaid.key`` (chmod 600), so the SQLite DB
backup never reveals broker access on its own.

Configuration (env):
    PLAID_CLIENT_ID
    PLAID_SECRET
    PLAID_ENV         sandbox|development|production (default sandbox)

Setup once:
    1. Create account at https://plaid.com (sandbox is free)
    2. Get CLIENT_ID + secret from Plaid dashboard
    3. Export both to env (or ~/.zshrc), restart dashboard
    4. UI → Settings → "Connect brokerage" → flows Plaid Link → token
       gets exchanged + stored encrypted in plaid_items table
    5. holdings_sync_daily cron runs every morning to refresh

All operations are no-ops if credentials missing — `is_configured()`
returns False and the rest of the platform proceeds normally.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


PLAID_BASE_URLS = {
    "sandbox":     "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production":  "https://production.plaid.com",
}


def _client_id() -> Optional[str]:
    return os.getenv("PLAID_CLIENT_ID") or None


def _secret() -> Optional[str]:
    return os.getenv("PLAID_SECRET") or None


def _base_url() -> str:
    env = (os.getenv("PLAID_ENV") or "sandbox").lower()
    return PLAID_BASE_URLS.get(env, PLAID_BASE_URLS["sandbox"])


def is_configured() -> bool:
    return bool(_client_id() and _secret())


# ── Token encryption (Fernet) ─────────────────────────────────────────


def _key_path() -> Path:
    p = Path.home() / ".neomind" / "fin" / "secrets" / "plaid.key"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_or_create_key() -> bytes:
    p = _key_path()
    if p.exists():
        return p.read_bytes()
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "cryptography lib required for Plaid token storage; "
            "pip install cryptography"
        ) from exc
    key = Fernet.generate_key()
    p.write_bytes(key)
    p.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return key


def _encrypt(plaintext: str) -> str:
    from cryptography.fernet import Fernet  # type: ignore
    return Fernet(_load_or_create_key()).encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    from cryptography.fernet import Fernet  # type: ignore
    return Fernet(_load_or_create_key()).decrypt(ciphertext.encode()).decode()


# ── Plaid REST API calls ──────────────────────────────────────────────


def _auth_payload() -> Dict[str, str]:
    cid = _client_id()
    sec = _secret()
    if not (cid and sec):
        raise RuntimeError("Plaid not configured — set PLAID_CLIENT_ID + PLAID_SECRET")
    return {"client_id": cid, "secret": sec}


async def link_token_create(user_id: str = "neomind-default") -> Dict[str, Any]:
    """Create a link_token. Frontend uses it to open Plaid Link UI."""
    payload = {
        **_auth_payload(),
        "user":          {"client_user_id": user_id},
        "client_name":   "NeoMind",
        "products":      ["investments"],
        "country_codes": ["US"],
        "language":      "en",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
        r = await c.post(f"{_base_url()}/link/token/create", json=payload)
        r.raise_for_status()
        return r.json()


async def exchange_public_token(public_token: str) -> Dict[str, Any]:
    """Exchange the Link-issued public_token for a long-lived access_token."""
    payload = {**_auth_payload(), "public_token": public_token}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
        r = await c.post(f"{_base_url()}/item/public_token/exchange", json=payload)
        r.raise_for_status()
        return r.json()


async def get_item(access_token: str) -> Dict[str, Any]:
    payload = {**_auth_payload(), "access_token": access_token}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
        r = await c.post(f"{_base_url()}/item/get", json=payload)
        r.raise_for_status()
        return r.json()


async def get_holdings(access_token: str) -> Dict[str, Any]:
    payload = {**_auth_payload(), "access_token": access_token}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as c:
        r = await c.post(f"{_base_url()}/investments/holdings/get", json=payload)
        r.raise_for_status()
        return r.json()


# ── Local persistence ────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def link_complete(public_token: str) -> Dict[str, Any]:
    """Frontend calls this after Plaid Link succeeds. Exchanges token,
    fetches item metadata, persists encrypted to plaid_items."""
    from agent.finance.persistence import connect, ensure_schema
    exchange = await exchange_public_token(public_token)
    access_token = exchange["access_token"]
    item_id = exchange["item_id"]
    item = await get_item(access_token)
    inst_id = (item.get("item") or {}).get("institution_id")
    inst_name = ""
    if inst_id:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as c:
                r = await c.post(
                    f"{_base_url()}/institutions/get_by_id",
                    json={**_auth_payload(),
                          "institution_id": inst_id,
                          "country_codes": ["US"]},
                )
                if r.status_code == 200:
                    inst_name = ((r.json() or {}).get("institution") or {}).get("name") or ""
        except Exception:
            pass
    ensure_schema()
    with connect() as conn:
        conn.execute(
            "INSERT INTO plaid_items "
            "(item_id, access_token_enc, institution_id, institution_name, "
            " created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET "
            "  access_token_enc = excluded.access_token_enc, "
            "  institution_name = excluded.institution_name",
            (item_id, _encrypt(access_token), inst_id, inst_name, _now()),
        )
    return {"item_id": item_id, "institution_name": inst_name, "ok": True}


def list_items() -> List[Dict[str, Any]]:
    from agent.finance.persistence import connect, ensure_schema
    ensure_schema()
    with connect() as conn:
        rows = conn.execute(
            "SELECT item_id, institution_id, institution_name, "
            "       last_sync_at, last_sync_status, consecutive_failures "
            "FROM plaid_items ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_item(item_id: str) -> bool:
    from agent.finance.persistence import connect, ensure_schema
    ensure_schema()
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM plaid_items WHERE item_id = ?", (item_id,))
        return cur.rowcount > 0


async def sync_all_items() -> Dict[str, Any]:
    """Pull holdings for every persisted item; reconcile into tax_lots.

    Reconciliation strategy (v1, conservative):
      - For each Plaid holding (ticker, total_quantity, cost_basis), if
        a single open lot already exists with same (ticker, account_id
        = 'plaid:<item_id>'), PATCH quantity + cost_basis.
      - Else: add_lot with account_id = 'plaid:<item_id>', open_date =
        today, open_price = cost_basis or live price.
      - Existing manual lots (account_id != 'plaid:*') are untouched —
        user's hand-tracking wins. Plaid only fills its own scope.

    Returns per-item status.
    """
    from agent.finance.persistence import connect, ensure_schema
    from agent.finance.positions import add_lot, list_lots, update_lot
    ensure_schema()
    results: List[Dict[str, Any]] = []
    if not is_configured():
        return {"status": "skipped", "reason": "PLAID_CLIENT_ID not set"}
    items = list_items()
    if not items:
        return {"status": "no_items"}
    for it in items:
        item_id = it["item_id"]
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT access_token_enc FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                ).fetchone()
            tok = _decrypt(row["access_token_enc"])
            h = await get_holdings(tok)
            holdings = h.get("holdings", [])
            securities = {s["security_id"]: s for s in h.get("securities", [])}
            n_patched = n_created = 0
            for holding in holdings:
                sec = securities.get(holding.get("security_id")) or {}
                ticker = (sec.get("ticker_symbol") or "").upper().strip()
                if not ticker:
                    continue
                qty = float(holding.get("quantity") or 0)
                cost = holding.get("cost_basis")
                if qty <= 0:
                    continue
                account_id = f"plaid:{item_id}"
                existing = list_lots(open_only=True, ticker=ticker,
                                     account_id=account_id)
                if existing:
                    lot = max(existing,
                              key=lambda l: float(l.get("open_quantity") or 0))
                    patch = {"open_quantity": qty}
                    if cost is not None:
                        patch["open_price"] = float(cost)
                    update_lot(int(lot["lot_id"]), patch)
                    n_patched += 1
                else:
                    add_lot(
                        symbol=ticker, market="US", asset_class="stock",
                        open_date=_now()[:10],
                        open_price=float(cost) if cost is not None else 0.0,
                        open_quantity=qty, open_fees=0.0,
                        account_id=account_id, notes="auto:plaid",
                    )
                    n_created += 1
            with connect() as conn:
                conn.execute(
                    "UPDATE plaid_items SET last_sync_at=?, last_sync_status='completed', "
                    "  consecutive_failures=0 WHERE item_id=?",
                    (_now(), item_id),
                )
            results.append({
                "item_id": item_id,
                "institution": it.get("institution_name"),
                "status": "completed",
                "patched": n_patched,
                "created": n_created,
            })
        except Exception as exc:
            logger.exception("plaid sync failed for %s", item_id)
            with connect() as conn:
                conn.execute(
                    "UPDATE plaid_items SET last_sync_at=?, last_sync_status='failed', "
                    "  consecutive_failures = consecutive_failures + 1 "
                    "WHERE item_id=?",
                    (_now(), item_id),
                )
            results.append({
                "item_id": item_id, "status": "failed", "error": str(exc),
            })
    return {"status": "completed", "items": results}
