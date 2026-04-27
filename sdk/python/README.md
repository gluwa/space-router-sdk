# SpaceRouter Python SDK

Python SDK for routing HTTP requests through the [Space Router](../../README.md) residential proxy network.

> **v1.5 testnet** — payment is now done by depositing SPACE into the
> on-chain `TokenPaymentEscrow` and signing per-request EIP-712
> receipts. The legacy `sr_live_*` API key flow is still supported on
> production until v1.5 ships there; on testnet it has been retired.
> See the [migration appendix](#migration-from-v14-api-key) at the
> bottom of this document.

## Installation

```bash
pip install spacerouter
pip install spacerouter-cli      # bundles the `spacerouter` command
```

The SDK depends on `eth-account` and `web3` for EIP-712 signing and
RPC calls; both are pulled in automatically.

## Quickstart (testnet, escrow flow)

This six-step path takes you from a fresh wallet to a paid proxied
request and back to a fully settled Leg 1 receipt. Every step is a
runnable shell snippet using only the bundled `spacerouter` CLI and
the SDK.

### 1. Set environment

```bash
# Testnet defaults — see internal-docs/v1.5-consumer-protocol.md §1.
export SR_GATEWAY_URL="https://spacerouter-proxy-gateway-test.fly.dev"
export SR_GATEWAY_MANAGEMENT_URL="https://spacerouter-proxy-gateway-test.fly.dev"
export SR_ESCROW_CHAIN_RPC="https://rpc.cc3-testnet.creditcoin.network"
export SR_ESCROW_CONTRACT_ADDRESS="0xC5740e4e9175301a24FB6d22bA184b8ec0762852"
export SR_ESCROW_CHAIN_ID="102031"

# Wallet — generate or import. Never commit this.
export SR_ESCROW_PRIVATE_KEY="0x..."
```

### 2. Fund a testnet wallet

You need both:

* native CTC on Creditcoin testnet (for gas) — use the team faucet.
* mock SPACE tokens (the ERC-20 the escrow charges in) — minted from
  `0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA`. Ask in Slack to be
  topped up if your balance reads zero.

```bash
# Confirm balances.
spacerouter escrow token-balance "$(python -c 'import os; from eth_account import Account; \
    print(Account.from_key(os.environ["SR_ESCROW_PRIVATE_KEY"]).address)')"
```

### 3. Approve the escrow as ERC-20 spender

A one-shot allowance covers many deposits.

```bash
# Allow the escrow to pull up to 100 SPACE on your behalf.
spacerouter escrow approve 100000000000000000000
```

`escrow deposit` will auto-approve when allowance is short, but
splitting the two transactions is cleaner for hardware-wallet
workflows or when you want a single large `approve(2**256-1)`.

### 4. Deposit SPACE into escrow

```bash
# 10 SPACE in wei.
spacerouter escrow deposit 10000000000000000000

# Verify.
spacerouter escrow balance "$(python -c 'import os; from eth_account import Account; \
    print(Account.from_key(os.environ["SR_ESCROW_PRIVATE_KEY"]).address)')"
```

### 5. Make a paid proxy request

```bash
spacerouter request get https://httpbin.org/ip --pay
```

`--pay` swaps the legacy API-key flow for the escrow-signed flow:
the CLI pulls a fresh challenge from
`{gateway}/auth/challenge`, attaches the four
`X-SpaceRouter-Payment-*` / `X-SpaceRouter-Challenge-*` headers, and
proxies the request. Add `--region US` etc. as before.

### 6. Sync Leg 1 receipts

After each paid request the gateway parks an unsigned Leg 1 receipt
addressed to your wallet. You sign it with EIP-712 and submit it
back via the broker.

```bash
# One-shot: list, sign, submit.
spacerouter receipts sync

# Or in one step alongside the request:
spacerouter request get https://httpbin.org/ip --pay --auto-settle

# Long-running settler that drains the queue every 30 s.
spacerouter receipts sync --watch 30

# Just look at what's pending without signing.
spacerouter receipts pending --json
```

## Programmatic SDK

```python
import asyncio
from spacerouter import SpaceRouter
from spacerouter.payment import SpaceRouterSPACE

PROXY = "https://spacerouter-proxy-gateway-test.fly.dev"
GATEWAY_MGMT = PROXY  # same host, separate routes
ESCROW = "0xC5740e4e9175301a24FB6d22bA184b8ec0762852"

async def main(private_key: str):
    consumer = SpaceRouterSPACE(
        gateway_url=GATEWAY_MGMT,
        proxy_url=PROXY,
        private_key=private_key,
        chain_id=102031,
        escrow_contract=ESCROW,
    )
    challenge = await consumer.request_challenge()
    headers = consumer.build_auth_headers(challenge)

    with SpaceRouter(consumer.address.lower(), gateway_url=PROXY) as cli:
        resp = cli.get("https://httpbin.org/ip", headers=headers)
        print(resp.json())

    # Settle the Leg 1 receipt the gateway just parked.
    print(await consumer.sync_receipts())

asyncio.run(main("0x..."))
```

The `SpaceRouterSPACE` client validates received receipts against your
local byte count, signs only after validation
(`sign_receipt_after_validation`), and exposes
`sync_receipts()` as a convenience wrapper around the Leg 1 broker.

## CLI cheat sheet

| Command | What it does |
|---|---|
| `spacerouter escrow balance <addr>` | Read on-chain escrow balance. |
| `spacerouter escrow token-balance <addr>` | Read undeposited SPACE balance. |
| `spacerouter escrow approve <wei> [--token ADDR]` | One-shot ERC-20 allowance for the escrow. |
| `spacerouter escrow deposit <wei>` | Deposit SPACE; auto-approves if needed. |
| `spacerouter escrow initiate-withdrawal <wei>` | Start the 5-day withdrawal timer. |
| `spacerouter escrow execute-withdrawal` | Pull funds out after the delay. |
| `spacerouter receipts pending [--json] [--limit N]` | List unsigned Leg 1 receipts. |
| `spacerouter receipts sync [--json] [--watch SECS]` | Sign all and submit. |
| `spacerouter receipts list [--client ADDR] [--json]` | Group pending receipts by tunnel. |
| `spacerouter receipts is-settled <client> <uuid>` | Check on-chain claim state. |
| `spacerouter request get <url> --pay` | Paid proxied GET. |
| `spacerouter request get <url> --pay --auto-settle` | Pay + settle Leg 1 in one step. |

For deeper troubleshooting (chain ID mismatch, allowance bugs,
EIP-712 signer mismatch, NTP clock skew, etc.) see
[`docs/consumer-quickstart.md`](docs/consumer-quickstart.md).

## Region Targeting

```python
client = SpaceRouter(payer_address, region="US")
jp_client = client.with_routing(region="JP")
```

## SOCKS5 Proxy

```python
client = SpaceRouter(
    payer_address,
    protocol="socks5",
    gateway_url="socks5://gateway:1080",
)
```

Requires the `socks` extra: `pip install spacerouter[socks]`.

## Error Handling

```python
from spacerouter.exceptions import (
    AuthenticationError,   # 407 - bad payment auth
    RateLimitError,        # 429
    NoNodesAvailableError, # 503
    UpstreamError,         # 502
)

try:
    response = client.get("https://example.com")
except RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
```

HTTP errors from the *target* website (404, 500, etc.) are not raised
as exceptions — only proxy-layer errors are.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gateway_url` | `https://gateway.spacerouter.org` | Proxy gateway URL (CONNECT) |
| `protocol` | `http` | `http` or `socks5` |
| `region` | `None` | 2-letter country code (ISO 3166-1 alpha-2) |
| `timeout` | `30.0` | Request timeout in seconds |

Escrow-mode payment is configured via env vars:
`SR_ESCROW_PRIVATE_KEY`, `SR_ESCROW_CONTRACT_ADDRESS`,
`SR_ESCROW_CHAIN_RPC`, `SR_ESCROW_CHAIN_ID`,
`SR_GATEWAY_MANAGEMENT_URL`.

## Migration from v1.4 (api-key)

The legacy API-key flow (`sr_live_*` keys passed via `--api-key` /
`SR_API_KEY` / the `SpaceRouter("sr_live_…")` positional argument) is
**dead on testnet** as of v1.5. On production it still works until v1.5
ships there. Plan your migration:

1. Generate a wallet keypair (any Ethereum-style 32-byte secp256k1
   key) and fund it with native CTC + mock SPACE on testnet.
2. Replace `SpaceRouter("sr_live_…")` with the escrow-signed flow shown
   above. The CLI flag is `--pay`; the `SpaceRouter` SDK is happy to
   accept the wallet address (lowercase 0x-hex) in place of an API key
   provided the request carries the four `X-SpaceRouter-*` headers
   that `SpaceRouterSPACE.build_auth_headers()` produces.
3. Once v1.5 ships to production, the API-key flow on prod will be
   retired the same way. Until then you can keep two code paths or
   use the wallet flow on testnet only.

The v1.5 protocol contract (EIP-712 domain, broker auth message, wire
formats) is locked at
`internal-docs/v1.5-consumer-protocol.md`. SDKs MUST produce
byte-identical signatures for the canonical test vector in §7.
