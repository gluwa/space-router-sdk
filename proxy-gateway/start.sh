#!/bin/sh
set -e

# Start tailscaled in userspace networking mode (required for containers)
tailscaled --state=/var/lib/tailscale/tailscaled.state \
           --socket=/var/run/tailscale/tailscaled.sock \
           --tun=userspace-networking &

# Wait for tailscaled to initialise
sleep 2

# Authenticate with the tailnet
if [ -n "$SR_TAILSCALE_AUTH_KEY" ]; then
    tailscale up --authkey="$SR_TAILSCALE_AUTH_KEY" --hostname="proxy-gateway"
    echo "Tailscale connected: $(tailscale ip -4)"
else
    echo "WARNING: SR_TAILSCALE_AUTH_KEY not set — Tailscale disabled"
fi

# Start the application
exec python -m app.main
