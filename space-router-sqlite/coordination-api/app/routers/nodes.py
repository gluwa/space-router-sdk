"""Node management endpoints for registering and managing proxy nodes."""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Remove the prefix to fix the 404 issue
router = APIRouter(tags=["nodes"])


class RegisterNodeRequest(BaseModel):
    endpoint_url: str
    node_type: str = "residential"  # "residential" or "external_provider"
    region: str | None = None
    label: str | None = None


class NodeInfo(BaseModel):
    id: str
    endpoint_url: str
    node_type: str
    status: str
    health_score: float
    region: str | None = None
    label: str | None = None
    created_at: str


@router.post("/nodes", status_code=201)
async def register_node(body: RegisterNodeRequest, request: Request) -> NodeInfo:
    db = request.app.state.db
    try:
        rows = await db.insert(
            "nodes",
            {
                "endpoint_url": body.endpoint_url,
                "node_type": body.node_type,
                "status": "online",
                "health_score": 1.0,
                "region": body.region,
                "label": body.label,
            },
            return_rows=True,
        )
        if not rows:
            raise Exception("No rows returned after insert")
    except Exception as e:
        logger.exception("Failed to register node: %s", e)
        raise HTTPException(status_code=500, detail="Failed to register node")
    return NodeInfo(**rows[0])


@router.get("/nodes")
async def list_nodes(request: Request) -> list[NodeInfo]:
    db = request.app.state.db
    try:
        rows = await db.select("nodes")
        return [NodeInfo(**r) for r in rows]
    except Exception as e:
        logger.exception("Failed to list nodes: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list nodes")


@router.patch("/nodes/{node_id}/status")
async def update_node_status(node_id: str, request: Request) -> dict:
    body = await request.json()
    status = body.get("status")
    if status not in ("online", "offline", "draining"):
        raise HTTPException(status_code=400, detail="Invalid status")
    db = request.app.state.db
    try:
        await db.update("nodes", {"status": status}, params={"id": node_id})
    except Exception as e:
        logger.exception("Failed to update node status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update node status")
    return {"ok": True}


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, request: Request) -> None:
    db = request.app.state.db
    try:
        await db.delete("nodes", params={"id": node_id})
    except Exception as e:
        logger.exception("Failed to delete node %s: %s", node_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete node")