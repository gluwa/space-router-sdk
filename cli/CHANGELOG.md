# Changelog

All notable changes to the SpaceRouter CLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2025-03-30

### Added

- **`identity` command group** — Wallet identity management for client authentication
  - `spacerouter identity generate` — Generate a new identity wallet with optional passphrase encryption
  - `spacerouter identity show` — Display the identity address from a keystore file
  - `spacerouter identity export` — Export identity to a new (optionally encrypted) keystore file
- Passphrase-based encryption support for identity keystores (Web3 secret storage format)
- JSON output for all identity commands (AI-agent-friendly)

## [0.1.1] — 2025-03-15

### Added

- Identity-based signing for node management
- Health probe compatibility

### Fixed

- Vouching signature format

## [0.1.0] — 2025-02-01

### Added

- Initial release
- `request` command group — Proxied HTTP requests
- `api-key` command group — API key management
- `node` command group — Node management
- `billing` command group — Billing and checkout
- `dashboard` command group — Dashboard data
- `config` command group — Configuration management
- `status` command — Service health check
- JSON-first output for AI agent consumption
