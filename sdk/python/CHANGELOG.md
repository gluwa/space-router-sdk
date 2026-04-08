# Changelog

All notable changes to the SpaceRouter Python SDK will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2025-03-30

### Added

- **`ClientIdentity` class** — Client-side identity wallet for wallet-authenticated requests
  - `ClientIdentity.generate()` — Create a new identity with optional keystore persistence
  - `ClientIdentity.from_private_key()` — Create from a raw hex private key
  - `ClientIdentity.from_keystore()` — Load from encrypted Web3 keystore or plaintext key file
  - `sign_message()` — EIP-191 personal sign for arbitrary messages
  - `sign_auth_header()` — Generate `X-Identity-Address`, `X-Identity-Signature`, `X-Timestamp` headers
  - `save_keystore()` — Export to encrypted (Web3 secret storage) or plaintext keystore
  - `payment_address` property — Optional payment wallet binding
- **Wallet-authenticated SpaceRouter clients** — `SpaceRouter(identity=...)` and `AsyncSpaceRouter(identity=...)` constructors accept `ClientIdentity` for wallet-based auth as an alternative to API keys
- `create_vouching_signature()` — Sign vouching messages linking staking and collection wallets

### Changed

- `SpaceRouter` / `AsyncSpaceRouter` now accept either `api_key` or `identity` (at least one required)
- `with_routing()` preserves identity across region switches

### Security

- Private keys stored internally as `eth_account.Account` objects, never as string attributes
- Python name mangling (`__account`) prevents accidental key exposure
- Keystore files written with `0o600` permissions (owner-only)
- Atomic writes via temp file + `os.replace()` prevent partial keystore corruption
- Temp file cleanup on write failure
- `O_CREAT | O_EXCL` flags on temp file prevent TOCTOU race conditions
- Encrypted keystores use scrypt KDF (N=262144, r=8, p=1) + AES-128-CTR
- Cached lowercase address avoids repeated string allocation

## [0.1.1] — 2025-03-15

### Added

- Identity-based signing for node management API
- `load_or_create_identity()`, `sign_request()`, `get_address()` functions
- Health probe compatibility

### Fixed

- Vouching signature format to include `collection_address`
- Made `gateway_ca_cert` optional on Node model

## [0.1.0] — 2025-02-01

### Added

- Initial release
- `SpaceRouter` sync client and `AsyncSpaceRouter` async client
- `SpaceRouterAdmin` and `AsyncSpaceRouterAdmin` for API key management
- HTTP and SOCKS5 proxy support
- Region targeting with ISO 3166-1 alpha-2 country codes
- Typed exceptions: `AuthenticationError`, `RateLimitError`, `NoNodesAvailableError`, `UpstreamError`
- `ProxyResponse` wrapper with `node_id` and `request_id` accessors
