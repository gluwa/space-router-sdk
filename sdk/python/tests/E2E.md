# Python SDK E2E test suite (testnet)

This directory ships two tracks of integration coverage:

| File | Network | Run when |
|---|---|---|
| `test_e2e_testnet.py` | live Creditcoin testnet + `spacerouter-proxy-gateway-test.fly.dev` | manually, before SDK releases |
| `test_e2e_helpers.py` | local only (mocks + canonical EIP-712 vector) | every PR (CI-safe) |
| `test_integration.py` | DEPRECATED — v1.4 API-key flow | never (skipped wholesale) |

CI does **not** auto-run `test_e2e_testnet.py`. The `e2e-testnet`
workflow in `.github/workflows/e2e-testnet.yml` is `workflow_dispatch`
only; a maintainer triggers it after a release branch is cut.

## Funding a fresh testnet wallet

The suite needs a wallet with:

1. **Native CTC** for gas on Creditcoin testnet (chain id `102031`).
   - Faucet: see the QA runbook in
     `internal-docs/qa-runbook-creditcoin-testnet.md` (the
     `Funding test wallets` section names the current dispenser).
2. **Mock SPACE** ERC-20 for the deposit test.
   - Token contract: `0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA`
   - The Mock token is mintable; the QA runbook lists the mint helper
     script and the operator wallet that owns the mint role.

The deposit test SKIPs cleanly when the Mock SPACE balance is below
`1 ether` (`10**18` wei), so a wallet with only gas will still pass the
read-only checks.

## Required and optional environment variables

```bash
# REQUIRED — funded consumer wallet (hex private key)
export SR_TESTNET_PRIVATE_KEY=0x...

# OPTIONAL — defaults shown
export SR_TESTNET_GATEWAY=https://spacerouter-proxy-gateway-test.fly.dev
export SR_TESTNET_GATEWAY_MGMT=https://spacerouter-proxy-gateway-test.fly.dev
export SR_ESCROW_CONTRACT_ADDRESS=0xC5740e4e9175301a24FB6d22bA184b8ec0762852
export SR_ESCROW_CHAIN_RPC=https://rpc.cc3-testnet.creditcoin.network
export SR_ESCROW_TOKEN_ADDRESS=0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA

# OPTIONAL — override the proxied target. Default is the Creditcoin
# testnet RPC ``/health`` endpoint, which is cheap and stable.
export SR_TESTNET_PROXY_TARGET=https://api.cc3-testnet.creditcoin.network/health
```

If `SR_TESTNET_PRIVATE_KEY` is missing, every live test SKIPs with a
pointer to this file. The canonical EIP-712 protocol vector
(`test_protocol_vector`) always runs because it is local-only.

## Running the suite

From the repo root:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e sdk/python -e cli
.venv/bin/pip install pytest pytest-asyncio httpx web3 eth-account

# Helpers + canonical vector — fast, CI-safe.
.venv/bin/pytest sdk/python/tests/test_e2e_helpers.py -v

# Full live suite — needs SR_TESTNET_PRIVATE_KEY exported.
.venv/bin/pytest -x sdk/python/tests/test_e2e_testnet.py -v
```

## Expected wall-clock

| Phase | Wall-clock |
|---|---|
| `test_balance_reads` | ~5 s (two contract `view` calls) |
| `test_deposit_round_trip` | ~30 s (approve + deposit, two block confirmations) |
| `test_paid_request_round_trip` | ~30 s (CONNECT + Leg 1 settle round-trip) |
| `test_isnonce_used_after_settle` | up to 120 s (waits for gateway `claimBatch`; SKIPs on timeout) |
| `test_withdrawal_initiate_then_cancel` | ~30 s (two state-changing tx + read-back) |
| `test_protocol_vector` | <100 ms (local) |
| **Total** | **2–3 min** typical, ~4 min worst case |

## Cleanup / triage

- All UUIDs minted by the suite are prefixed `e2e-py-<unix-ts>-`. Search
  the gateway DB or `pending_client_receipts` table by that prefix to
  audit or purge stale entries from a flaky run.
- The withdrawal round-trip is non-destructive: it requests a 0-amount
  withdrawal (a no-op on the contract) and then cancels. If the SDK's
  client-side guard rejects 0, the helper falls back to `1 wei` and
  cancels regardless — see the comment in `_initiate_withdrawal_zero`.

## When this suite goes red

- `RPC errors / timeouts` — the testnet RPC is occasionally throttled.
  The fixtures use 60–120 s polling windows. Re-run the failing test
  alone before opening an incident.
- `0 receipts accepted by /leg1/sign` — usually means the gateway flushed
  the receipt to a different DB shard (multi-machine on Fly). Check
  `feedback_escrow_dev.md` in the maintainer's notes.
- `signer_mismatch` rejections — the wallet env var doesn't match the
  EIP-712 typed-data signer. Almost always a checksum-vs-lowercase
  mismatch — `EscrowClient` and `SpaceRouterSPACE` both normalise, so
  this is rare.
