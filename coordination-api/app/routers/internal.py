"""Internal endpoints consumed by the proxy-gateway.

These are the three endpoints that make up the proxy-gateway ↔ coordination-api contract:
  POST /internal/auth/validate
  GET  /internal/route/select
  POST /internal/route/report
"""

import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.dependencies import verify_internal_secret
from app.services.auth_service import AuthService
from app.services.routing_service import RoutingService

logger = logging.getLogger(__name__)

# Remove the prefix from the router to fix 404 issues
router = APIRouter(dependencies=[Depends(verify_internal_secret)])


# --- Auth ---


class AuthValidateRequest(BaseModel):
    key_hash: str


class AuthValidateResponse(BaseModel):
    valid: bool
    api_key_id: str | None = None
    rate_limit_rpm: int | None = None


@router.post("/internal/auth/validate")
async def validate_auth(body: AuthValidateRequest, request: Request) -> AuthValidateResponse:
    auth_service: AuthService = request.app.state.auth_service
    result = await auth_service.validate_key_hash(body.key_hash)
    if result is None:
        return AuthValidateResponse(valid=False)
    return AuthValidateResponse(
        valid=True,
        api_key_id=result["api_key_id"],
        rate_limit_rpm=result["rate_limit_rpm"],
    )


# --- Route Selection ---


class RouteSelectResponse(BaseModel):
    node_id: str
    endpoint_url: str


@router.get("/internal/route/select")
async def select_route(request: Request, response: Response) -> RouteSelectResponse:
    routing_service: RoutingService = request.app.state.routing_service
    node = await routing_service.select_node()
    if node is None:
        response.status_code = 503
        return RouteSelectResponse(node_id="", endpoint_url="")
    return RouteSelectResponse(node_id=node.node_id, endpoint_url=node.endpoint_url)


# --- Route Report ---


class RouteReportRequest(BaseModel):
    node_id: str
    success: bool
    latency_ms: int
    bytes: int


@router.post("/internal/route/report", status_code=200)
async def report_route(body: RouteReportRequest, request: Request) -> dict:
    routing_service: RoutingService = request.app.state.routing_service
    await routing_service.report_outcome(
        node_id=body.node_id,
        success=body.success,
        latency_ms=body.latency_ms,
        bytes_transferred=body.bytes,
    )
    return {"ok": True}