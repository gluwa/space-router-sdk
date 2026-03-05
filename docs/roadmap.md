# Space Router Roadmap — StarMesh Integration

## Phase One: Space Router MVP Launch — March 2026

Launch without payments. Agent client libraries in Python and JavaScript supporting HTTP and SOCKS5. Coordination API and proxy gateway already live on Fly.io. Bootstrap with internal nodes plus ProxyJet and ProxyChat as fallback supply. Agent sees residential IPs, datacenter-blocking problems solved. Proves market demand.

## Phase Two: Entry Nodes — Post-Launch

StarMesh entry nodes replace the cloud gateway. Agent client library interface stays the same, but traffic now routes through distributed entry nodes. Node registration and on-chain reputation begin. Test incentive payouts and operator economics.

## Phase Three: Multi-Hop Routing — Later Quarter

Full three-hop circuits with middle and exit nodes. Privacy layer activates. Coordination API starts being sidelined. Agents still use the same client library — routing complexity hidden underneath.

## Phase Four: Full Decentralization — End Goal

Coordination API and gateway retired. Agents read node registry directly from blockchain via the client library, build circuits themselves. On-chain reputation and payment settlement fully live. Minimal on-chain — only transactions. Everything else subjective and off-chain.

## StarMesh Integration Strategy

StarMesh becomes the underlying routing protocol and incentive layer for all node-to-node communication.

In Phase Two, entry nodes adopt StarMesh's wire protocol and on-chain node registry. By Phase Three, the full three-hop circuit model (entry-middle-exit) aligns with StarMesh's guard-middle-exit architecture. The client SDK abstracts StarMesh complexity — agents don't need to know they're using onion routing; they just request a route and get a circuit.

Payment settlement and reputation tracking leverage StarMesh's blockchain-based transaction model: only immutable facts live on-chain, subjective reputation assessment happens off-chain. By Phase Four, StarMesh's decentralized node discovery replaces the centralized coordination API entirely.

The transition is seamless from the agent's perspective because the client SDK interface never changes — only the backend swaps from centralized routing to distributed StarMesh circuits.

## Architecture Principles Throughout

- **Node layer** handles routing.
- **Blockchain layer** handles immutable transaction history only.
- **Client SDK** remains the stable interface across all phases.
- **Progressive decentralization** — swap pieces, don't rewrite.

## Delivery Over Decentralization

Early phases prioritize reliability and low latency over full decentralization. Centralized components (coordination API, gateway) remain as long as they ensure fast, consistent delivery. Decentralization is phased in as the network matures and proves itself. This pragmatic approach lets agents trust Space Router before trusting a fully distributed system.

Circuit depth is configurable — agents can choose one hop for speed, three for standard privacy, six for maximum security. The flexibility lets different use cases optimize for their own priorities without sacrificing the network's core value proposition.
