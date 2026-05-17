"""FastAPI router for Plaid integration."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class PublicTokenBody(BaseModel):
    public_token: str


def build_plaid_router() -> APIRouter:
    router = APIRouter(prefix="/api/integrations/plaid", tags=["plaid"])

    @router.get("/status")
    def status_endpoint() -> Dict[str, Any]:
        from agent.finance.integrations.plaid import is_configured, list_items
        return {
            "configured": is_configured(),
            "items":      list_items() if is_configured() else [],
            "setup_hint": ("Set PLAID_CLIENT_ID + PLAID_SECRET in env, "
                           "restart dashboard, then click Connect."),
        }

    @router.post("/link_token")
    async def link_token_endpoint() -> Dict[str, Any]:
        from agent.finance.integrations.plaid import is_configured, link_token_create
        if not is_configured():
            raise HTTPException(400, "Plaid not configured")
        return await link_token_create()

    @router.post("/exchange")
    async def exchange_endpoint(body: PublicTokenBody) -> Dict[str, Any]:
        from agent.finance.integrations.plaid import is_configured, link_complete
        if not is_configured():
            raise HTTPException(400, "Plaid not configured")
        return await link_complete(body.public_token)

    @router.post("/sync")
    async def sync_endpoint() -> Dict[str, Any]:
        from agent.finance.integrations.plaid import is_configured, sync_all_items
        if not is_configured():
            raise HTTPException(400, "Plaid not configured")
        return await sync_all_items()

    @router.delete("/items/{item_id}")
    def delete_item_endpoint(item_id: str) -> Dict[str, Any]:
        from agent.finance.integrations.plaid import delete_item
        ok = delete_item(item_id)
        return {"ok": ok, "item_id": item_id}

    return router
