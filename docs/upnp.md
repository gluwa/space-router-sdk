# UPnP / NAT-PMP Setup

Home Nodes run on residential machines behind NAT routers. UPnP (Universal Plug and Play) and NAT-PMP (NAT Port Mapping Protocol) automatically configure port forwarding on the router so the Proxy Gateway can reach Home Nodes.

## How it works

1. On startup, the Home Node discovers the router via UPnP/NAT-PMP
2. It requests a port mapping (e.g. external port 9090 → internal port 9090)
3. The router's external IP and mapped port are registered with the Coordination API
4. The Proxy Gateway connects to the Home Node via the router's public IP
5. On shutdown, the port mapping is removed

## Requirements

- The router must support UPnP IGD or NAT-PMP (most consumer routers do)
- UPnP must be enabled in the router's settings
- The `miniupnpc` Python package (installed automatically via requirements.txt)

## Configuration

UPnP is enabled by default. Set `SR_UPNP_ENABLED=false` to disable it and fall back to manual port forwarding (direct mode).

The lease duration controls how long the port mapping persists on the router. The Home Node automatically renews the mapping before it expires:

```bash
export SR_UPNP_ENABLED=true        # Enable UPnP (default)
export SR_UPNP_LEASE_DURATION=3600  # Lease duration in seconds (default: 3600)
```

## Direct mode (manual port forwarding)

If UPnP is unavailable or disabled, Home Nodes fall back to direct mode. In this case, you must manually configure port forwarding on your router to forward TCP port 9090 to the Home Node machine.
