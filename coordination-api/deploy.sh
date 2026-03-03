#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Running tests..."
SR_USE_SQLITE=true SR_INTERNAL_API_SECRET=test-secret pytest tests/ -v

echo ""
echo "==> Deploying to Fly.io..."
flyctl deploy --remote-only

echo ""
echo "==> Done! Checking status..."
flyctl status
