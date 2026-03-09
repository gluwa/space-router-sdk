# SpaceRouter Python SDK

Python SDK for routing HTTP requests through the [Space Router](../../README.md) residential proxy network.

## Installation

```bash
pip install spacerouter

# With SOCKS5 support
pip install spacerouter[socks]
```

## Quick Start

```python
from spacerouter import SpaceRouter

with SpaceRouter("sr_live_YOUR_API_KEY", gateway_url="http://gateway:8080") as client:
    response = client.get("https://httpbin.org/ip")
    print(response.json())       # {"origin": "residential-ip"}
    print(response.node_id)      # node that handled the request
    print(response.request_id)   # unique request ID for tracing
```

## Async Usage

```python
from spacerouter import AsyncSpaceRouter

async with AsyncSpaceRouter("sr_live_YOUR_API_KEY") as client:
    response = await client.get("https://httpbin.org/ip")
    print(response.json())
```

## IP Targeting

Route requests through specific IP types or geographic regions:

```python
# Target residential IPs in the US
client = SpaceRouter("sr_live_xxx", ip_type="residential", region="US")

# Target mobile IPs in South Korea
client = SpaceRouter("sr_live_xxx", ip_type="mobile", region="Seoul, KR")

# Change routing on the fly
mobile_client = client.with_routing(ip_type="mobile", region="JP")
```

Available IP types: `residential`, `mobile`, `datacenter`, `business`

## SOCKS5 Proxy

```python
client = SpaceRouter(
    "sr_live_xxx",
    protocol="socks5",
    gateway_url="socks5://gateway:1080",
)
response = client.get("https://httpbin.org/ip")
```

Requires the `socks` extra: `pip install spacerouter[socks]`

## API Key Management

```python
from spacerouter import SpaceRouterAdmin

with SpaceRouterAdmin("http://localhost:8000") as admin:
    # Create a key (raw value only available here)
    key = admin.create_api_key("my-agent", rate_limit_rpm=120)
    print(key.api_key)  # sr_live_...

    # List keys
    for k in admin.list_api_keys():
        print(k.name, k.key_prefix, k.is_active)

    # Revoke a key
    admin.revoke_api_key(key.id)
```

Async variant: `AsyncSpaceRouterAdmin`

## Error Handling

```python
from spacerouter import SpaceRouter
from spacerouter.exceptions import (
    AuthenticationError,   # 407 - invalid API key
    RateLimitError,        # 429 - rate limit exceeded
    NoNodesAvailableError, # 503 - no residential nodes online
    UpstreamError,         # 502 - target unreachable via node
)

with SpaceRouter("sr_live_xxx") as client:
    try:
        response = client.get("https://example.com")
    except RateLimitError as e:
        print(f"Rate limited, retry after {e.retry_after}s")
    except NoNodesAvailableError:
        print("No nodes available, try again later")
    except UpstreamError as e:
        print(f"Node {e.node_id} could not reach target")
    except AuthenticationError:
        print("Check your API key")
```

Note: HTTP errors from the target website (e.g. 404, 500) are **not** raised as exceptions. Only proxy-layer errors produce exceptions.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_key` | (required) | API key (`sr_live_...`) |
| `gateway_url` | `http://localhost:8080` | Proxy gateway URL |
| `protocol` | `http` | `http` or `socks5` |
| `ip_type` | `None` | IP type filter |
| `region` | `None` | Region filter (substring match) |
| `timeout` | `30.0` | Request timeout in seconds |
