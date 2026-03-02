from fastapi import Header, HTTPException, Request


async def verify_internal_secret(request: Request, authorization: str = Header()) -> None:
    """Verify the shared secret for internal endpoints (proxy-gateway → coordination-api)."""
    secret = request.app.state.settings.INTERNAL_API_SECRET
    if not secret:
        return  # No secret configured — skip in dev
    expected = f"Bearer {secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid internal secret")
