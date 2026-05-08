# Consumer Quickstart Troubleshooting (v1.5)

This document is the deep-dive companion to the [SDK README](../README.md).
Read the README first; come here when something's wrong.

The authoritative protocol contract (EIP-712 domain, broker auth, wire
formats) lives at `internal-docs/v1.5-consumer-protocol.md`. Anything
that contradicts it is a bug in this guide.

---

## Two URLs, two purposes

Before anything else: the SDK takes **two** gateway URLs, and getting
them mixed up is the single most common configuration bug.

* **`proxy_url`** (env: `SR_GATEWAY_URL`; JS: `gatewayUrl` on
  `SpaceRouter`) is the **proxy** endpoint — typically
  `https://gateway.example.com` on port 443 or 8080. It only handles
  HTTP `CONNECT` for your tunnelled application traffic.
* **`gateway_url`** / **`management_url`** (env:
  `SR_GATEWAY_MANAGEMENT_URL`; JS: `gatewayMgmtUrl` on
  `SpaceRouterSPACE`) is the **management API** endpoint — typically
  the same hostname on port 8081. It serves `/auth/challenge` and
  `/leg1/...`.

They are two different ports on the same gateway server. Sending
management requests to the proxy listener returns **HTTP 407** because
the proxy port only handles `CONNECT`.

```bash
# Typical split-port deployment:
export SR_GATEWAY_URL="https://gateway.example.com"           # :443 / :8080
export SR_GATEWAY_MANAGEMENT_URL="https://gateway.example.com:8081"
```

If your deployment exposes both proxy and management on the same port
(some single-port test gateways do), set both vars to the same URL —
otherwise keep them split.

---

## If you get HTTP 407 (you swapped the URLs)

**Symptom.** `request_challenge()` raises `HTTP 407 Proxy
Authentication Required`. Or every `/leg1/...` call returns 407. Or
`spacerouter receipts sync` reports 407 against `/leg1/pending`.

**Cause.** You pointed `SR_GATEWAY_MANAGEMENT_URL` (or the SDK's
`gateway_url` / `management_url` parameter) at the **proxy** port
instead of the **management** port. The proxy listener only accepts
`CONNECT` — every other verb is answered with 407.

**Fix.**

```bash
# Confirm both URLs first.
echo "$SR_GATEWAY_URL"             # should be the proxy listener (:443/:8080)
echo "$SR_GATEWAY_MANAGEMENT_URL"  # should be the management listener (:8081)

# Probe the management endpoint directly — it should return JSON, not 407.
curl -i "$SR_GATEWAY_MANAGEMENT_URL/auth/challenge"
# 200 OK  + {"challenge": "..."}        — correct
# 407 Proxy Authentication Required     — wrong port, fix the env var
```

If you only have one URL handy and the gateway uses split ports, the
management URL is almost always `${SR_GATEWAY_URL%/}:8081` — check
with the deployment owner before assuming.

---

## Chain ID mismatch (`expect 102031`)

**Symptom.** EIP-712 signatures recover to a different address than
expected; `/leg1/sign` returns `eip712_signer_mismatch`. Or the
escrow contract reverts a `deposit` with no obvious reason.

**Cause.** The signer is using a different `chainId` than the on-chain
contract was deployed at. Creditcoin testnet is **102031**, NOT 1,
NOT 102030, NOT 102032. The chain ID is bound into the EIP-712 domain
hash; even a single-bit difference invalidates every signature.

**Fix.**

```bash
# CLI:
export SR_ESCROW_CHAIN_ID=102031

# SDK:
SpaceRouterSPACE(..., chain_id=102031, ...)
```

If you're using a custom RPC, verify it actually serves the right
chain:

```bash
curl -s "$SR_ESCROW_CHAIN_RPC" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_chainId","id":1,"params":[]}'
# {"jsonrpc":"2.0","id":1,"result":"0x18e4f"}    # 0x18e4f == 102031
```

---

## Allowance not set (`token_balance > 0` but `deposit` reverts)

**Symptom.** `escrow token-balance` shows you hold SPACE, but
`escrow deposit` reverts. Web3 may surface only "execution reverted"
with no reason string.

**Cause.** `deposit(amount)` calls `transferFrom` on the SPACE ERC-20.
That requires the consumer to have approved the escrow as spender for
at least `amount`. The SDK's `EscrowClient.deposit` auto-approves when
allowance is short, but if you're using `web3.py` directly or a UI
wallet, you have to approve first.

**Fix.**

```bash
# Set a generous allowance once.
spacerouter escrow approve 100000000000000000000000   # 100k SPACE

# Then deposit as many times as you like.
spacerouter escrow deposit 10000000000000000000        # 10 SPACE
```

You can also verify allowance by reading the ERC-20 directly:

```python
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://rpc.cc3-testnet.creditcoin.network"))
erc20 = w3.eth.contract(
    address="0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA",
    abi=[{"name": "allowance", "type": "function", "stateMutability": "view",
          "inputs": [{"type": "address"}, {"type": "address"}],
          "outputs": [{"type": "uint256"}]}],
)
print(erc20.functions.allowance(YOUR_WALLET, ESCROW_PROXY).call())
```

---

## `eip712_signer_mismatch` from `/leg1/sign`

**Symptom.** `receipts sync` returns
`{"rejected": [{..., "reason": "eip712_signer_mismatch"}]}` for every
receipt. Or the gateway logs it on Leg 2 claim attempts.

The recovered signer doesn't equal the consumer wallet the gateway
expects.

**Common causes (in rough order):**

1. **Address casing bug.** The `clientAddress` field in the receipt
   struct must be the **checksummed** form when fed to
   `eth_account` / viem. Some SDK code paths lowercase it before
   signing — that produces a *different* hash. The wire format outside
   the EIP-712 typed data is lowercase, but the typed-data encoder
   needs the canonical (EIP-55) form. The reference Python
   implementation in `spacerouter/payment/eip712.py` calls
   `to_checksum_address()` defensively — don't disable that.
2. **Wrong domain.** The domain `name`, `version`, `chainId`, and
   `verifyingContract` must match the on-chain contract exactly.
   On testnet: `("TokenPaymentEscrow", "1", 102031, "0xC5740e4e9175301a24FB6d22bA184b8ec0762852")`.
3. **Clock skew.** See next section.
4. **`nodeAddress` packed wrong.** It's `bytes32(stakingAddress)` —
   zero-left-pad the 20-byte staking address to 32 bytes. Easy to mix
   up with the node's identity key (different value).
5. **`requestUUID` case-folded.** The gateway emits a specific
   UUID; do not lowercase or normalise it on signing — it's hashed
   as a UTF-8 string.

**Verify locally** with the canonical test vector in §7 of the
protocol contract. If your SDK's signature for that vector doesn't
match `0x15cbab3e…41c`, you have a bug; if it does match, the bug is
in your wiring (one of the bullets above), not the signer.

---

## 60-second timestamp window (NTP requirement)

**Symptom.** `/leg1/pending` or `/leg1/sign` returns 401/403, or
intermittent failures only on some machines (e.g. CI runners,
laptops that have been sleeping).

**Cause.** The Leg 1 broker auth message is
`space-router:leg1-<verb>:<addr>:<ts>` with `<ts>` as unix-seconds.
The gateway tolerates ±60 s. Drift outside that window — typically a
machine that hasn't run NTP recently — is rejected.

**Fix.**

```bash
# macOS / Linux: confirm NTP sync.
date -u
# Compare to:
curl -sI https://google.com | grep -i '^date:'
# If the two diverge by more than ~30s, fix system NTP.
```

The SDK should surface a typed `TimestampExpiredError` when this
happens — if you see a generic `httpx.HTTPStatusError` instead, please
file an issue.

---

## Connection-refused on `:443` (gateway URL typos)

**Symptom.**
`httpcore.ConnectError: [Errno 61] Connection refused` (or `61: ECONNREFUSED`)
when the CLI proxies a request.

**Cause.** Almost always a malformed `SR_GATEWAY_URL`. The proxy is a
**CONNECT** proxy on port 443 of the gateway host you point at. Common
typos:

* `http://...` instead of `https://...` — the gateway only speaks TLS
  on 443.
* Trailing slashes interpreted by your shell — quote the value:
  `export SR_GATEWAY_URL="https://your-gateway.example.com"`.
* Pointing at `:8081` (the management port) — that's only used by
  `SR_GATEWAY_MANAGEMENT_URL` and the broker; the proxy CONNECT lives
  on 443.
* Pointing at a stale local dev URL (`http://localhost:8080`) when
  the gateway isn't running locally.

**Fix.**

```bash
export SR_GATEWAY_URL="https://your-gateway.example.com"
export SR_GATEWAY_MANAGEMENT_URL="https://your-gateway.example.com"
spacerouter status        # quick sanity check
```

---

## "All receipts rejected as `not_pending`" (queue drained by another client)

**Symptom.** `receipts sync` returns
`{"accepted": [], "rejected": [{..., "reason": "not_pending"}, ...]}`
for every receipt. Or you're running two settlers in parallel and one
keeps coming up empty.

**Cause.** The Leg 1 broker has *atomic* `consume`: a receipt can
only transition from `pending` → `signed` once. If another instance of
your settler (or another machine, or a stale tab) drained the queue
between `GET /leg1/pending` and `POST /leg1/sign`, every UUID you
present has already been consumed and now reports `not_pending`.

This is a normal operating condition — the protocol contract calls it
out in §9 ("Negative-path expectations") explicitly. The SDK MUST
surface every reason but MUST NOT raise unless the caller opted in to
strict mode.

**Resolutions:**

* **Single settler.** Run `receipts sync --watch 30` from one process
  and stop running it elsewhere. Idempotent and lock-free.
* **Multiple settlers.** Acceptable on the same wallet — duplicate
  signatures are no-ops — but expect `not_pending` rejections to be
  the steady state, not an error.
* **Check on-chain settlement** to confirm the receipt did make it
  through:

  ```bash
  spacerouter receipts is-settled "$WALLET" "$REQUEST_UUID"
  ```

  If that returns `settled_on_chain: true`, the rejection from
  `/leg1/sign` was working as intended.

---

## Other useful checks

* `spacerouter status` — basic health probe to gateway + coord API.
* `spacerouter escrow withdrawal-delay` — confirms the contract's
  current delay (5 days on testnet).
* `spacerouter receipts pending --json | jq '.receipts | length'` —
  count parked receipts at a glance.
* `spacerouter --version` — pin a known-good CLI version when
  reporting bugs.

If a problem isn't covered here, open an issue with:

1. Output of `spacerouter --version` and the `pip show spacerouter`
   version.
2. Wallet address (NOT the private key) and the request UUID(s)
   involved.
3. Full JSON output of the failing command (`--json` flag) plus any
   gateway error body.
