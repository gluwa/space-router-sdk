import json
from datetime import datetime, timezone


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


def build_http_response(
    status_code: int,
    status_text: str,
    body: dict,
    headers: dict[str, str] | None = None,
) -> bytes:
    body_bytes = json.dumps(body).encode()
    all_headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body_bytes)),
        "Date": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "Connection": "close",
    }
    if headers:
        all_headers.update(headers)

    header_lines = "".join(f"{k}: {v}\r\n" for k, v in all_headers.items())
    return f"HTTP/1.1 {status_code} {status_text}\r\n{header_lines}\r\n".encode() + body_bytes


def proxy_auth_required(request_id: str | None = None) -> bytes:
    headers = {}
    if request_id:
        headers["X-SpaceRouter-Request-Id"] = request_id
    headers["Proxy-Authenticate"] = 'Basic realm="SpaceRouter"'
    return build_http_response(
        407,
        "Proxy Authentication Required",
        {"error": "proxy_auth_required", "message": "Valid API key required"},
        headers,
    )


def rate_limited(retry_after_seconds: int, request_id: str | None = None) -> bytes:
    headers = {"Retry-After": str(retry_after_seconds)}
    if request_id:
        headers["X-SpaceRouter-Request-Id"] = request_id
    return build_http_response(
        429,
        "Too Many Requests",
        {
            "error": "rate_limited",
            "message": "Rate limit exceeded",
            "retry_after_seconds": retry_after_seconds,
        },
        headers,
    )


def upstream_error(request_id: str | None = None, node_id: str | None = None) -> bytes:
    headers = {}
    if request_id:
        headers["X-SpaceRouter-Request-Id"] = request_id
    if node_id:
        headers["X-SpaceRouter-Node"] = node_id
    return build_http_response(
        502,
        "Bad Gateway",
        {"error": "upstream_error", "message": "Target unreachable via residential node"},
        headers,
    )


def no_nodes_available(request_id: str | None = None) -> bytes:
    headers = {}
    if request_id:
        headers["X-SpaceRouter-Request-Id"] = request_id
    return build_http_response(
        503,
        "Service Unavailable",
        {"error": "no_nodes_available", "message": "No residential nodes currently available"},
        headers,
    )


def bad_request(message: str, request_id: str | None = None) -> bytes:
    headers = {}
    if request_id:
        headers["X-SpaceRouter-Request-Id"] = request_id
    return build_http_response(
        400,
        "Bad Request",
        {"error": "bad_request", "message": message},
        headers,
    )