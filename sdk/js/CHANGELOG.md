# Changelog

All notable changes to the SpaceRouter JavaScript SDK will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2025-03-30

### Added

- **`ClientIdentity` class** — Client-side identity wallet for wallet-authenticated requests
  - `ClientIdentity.fromPrivateKey()` — Create from a raw hex private key
  - `ClientIdentity.generate()` — Create a new identity with optional keystore persistence
  - `ClientIdentity.fromKeystore()` — Load from encrypted Web3 keystore or plaintext key file
  - `signMessage()` — EIP-191 personal sign for arbitrary messages (async, via viem)
  - `signAuthHeaders()` — Generate `X-Identity-Address`, `X-Identity-Signature`, `X-Timestamp` headers
  - `saveKeystore()` — Export to encrypted (Web3 secret storage) or plaintext keystore
  - `paymentAddress` property — Optional payment wallet binding
- **Wallet-authenticated SpaceRouter** — `new SpaceRouter({ identity })` constructor accepts `ClientIdentity` for wallet-based auth as an alternative to API keys
- **Encrypted keystore support** — Full Web3 Secret Storage implementation using Node.js `crypto` (scrypt + aes-128-ctr + SHA3-256 MAC)
- `createVouchingSignature()` — Sign vouching messages linking staking and collection wallets
- Cross-SDK keystore compatibility — keystores are interchangeable with the Python SDK

### Changed

- `SpaceRouter` constructor now accepts either an API key string or an options object with `identity`
- `withRouting()` preserves identity across region switches

### Security

- Private key stored as ES2022 `#privateKey` class field — inaccessible at runtime via `Object.keys()`, `JSON.stringify()`, or property enumeration
- Keystore files written with `0o600` permissions (owner-only)
- Input validation on `signAuthHeaders()` timestamp parameter (`TypeError` on non-finite values)
- Cached lowercase address avoids repeated string allocation
- Encrypted keystores use scrypt KDF (N=262144, r=8, p=1) + AES-128-CTR with SHA3-256 MAC verification

## [0.1.1] — 2025-03-15

### Added

- Identity-based signing for node management API
- `loadOrCreateIdentity()`, `signRequest()`, `getAddress()` functions
- Health probe compatibility

### Fixed

- Vouching signature format to include `collectionAddress`
- Made `gatewayCaCert` optional on Node model

## [0.1.0] — 2025-02-01

### Added

- Initial release
- `SpaceRouter` proxy client with HTTP and SOCKS5 support
- `SpaceRouterAdmin` for API key management
- Region targeting with ISO 3166-1 alpha-2 country codes
- Typed exceptions: `AuthenticationError`, `RateLimitError`, `NoNodesAvailableError`, `UpstreamError`
- `ProxyResponse` wrapper with `nodeId` and `requestId` accessors
