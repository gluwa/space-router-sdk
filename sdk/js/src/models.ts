// ---------------------------------------------------------------------------
// Routing & filtering types
// ---------------------------------------------------------------------------

/** IP address type for filtering proxy nodes. */
export type IpType = "residential" | "mobile" | "datacenter" | "business";

/** Node operational status (for status updates). Nodes go online via health probes. */
export type NodeStatus = "offline" | "draining";

/** How a node connects to the network. */
export type NodeConnectivityType = "direct" | "upnp" | "external_provider";

/** Options for the {@link SpaceRouter} constructor. */
export interface SpaceRouterOptions {
  /** Proxy gateway URL. Default: `"https://gateway.spacerouter.org"` */
  gatewayUrl?: string;
  /** Proxy protocol. Default: `"http"` */
  protocol?: "http" | "socks5";
  /** Region filter — 2-letter country code (ISO 3166-1 alpha-2, e.g. "US"). */
  region?: string;
  /** IP type filter — restrict to a specific address type. */
  ipType?: IpType;
  /** Request timeout in milliseconds. Default: `30_000` */
  timeout?: number;
  /**
   * Set to `false` to skip TLS certificate verification for the gateway
   * connection. Use only for development against a test gateway with a
   * self-signed certificate. Default `true`.
   *
   * Note: this currently affects the HTTPS gateway path only. The SOCKS5
   * path does not propagate this option — set
   * `NODE_TLS_REJECT_UNAUTHORIZED=0` in the environment if you need to
   * disable verification for SOCKS5 against a self-signed gateway.
   */
  verify?: boolean;
}

/** Options for the {@link SpaceRouterAdmin} constructor. */
export interface SpaceRouterAdminOptions {
  /** Request timeout in milliseconds. Default: `10_000` */
  timeout?: number;
}

/** API key returned at creation time (`POST /api-keys`). */
export interface ApiKey {
  id: string;
  name: string;
  /** Raw API key value — only available at creation time. */
  api_key: string;
  rate_limit_rpm: number;
}

/** API key metadata from list endpoint (`GET /api-keys`). */
export interface ApiKeyInfo {
  id: string;
  name: string;
  /** First 12 characters of the key. */
  key_prefix: string;
  rate_limit_rpm: number;
  is_active: boolean;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Node management
// ---------------------------------------------------------------------------

/**
 * Proxy node returned by `GET /nodes` and `POST /nodes`.
 *
 * v0.2.0 uses three role-specific wallet addresses. The legacy
 * `wallet_address` field is kept for backward compatibility.
 */
export interface Node {
  id: string;
  endpoint_url: string;
  public_ip: string;
  connectivity_type: string;
  node_type: string;
  status: string;
  health_score: number;
  region: string;
  label: string | null;
  ip_type: string;
  ip_region: string;
  as_type: string;
  identity_address: string;
  staking_address: string;
  collection_address: string;
  /** @deprecated Use identity_address. Kept for backward compatibility. */
  wallet_address: string;
  created_at: string;
  gateway_ca_cert?: string;
}

/** Normalize a raw node response, filling v0.2.0 fields from legacy wallet_address if needed. */
export function normalizeNode(raw: Record<string, unknown>): Node {
  const wallet = (raw.wallet_address ?? raw.identity_address ?? "") as string;
  return {
    ...raw,
    identity_address: (raw.identity_address ?? wallet) as string,
    staking_address: (raw.staking_address ?? wallet) as string,
    collection_address: (raw.collection_address ?? wallet) as string,
    wallet_address: wallet,
  } as Node;
}

// ---------------------------------------------------------------------------
// Staking registration
// ---------------------------------------------------------------------------

/** Challenge returned by `POST /nodes/register/challenge`. */
export interface RegisterChallenge {
  nonce: string;
  expires_in: number;
}

/** Result of `POST /nodes/register/verify`. */
export interface RegisterResult {
  status: string;
  node_id: string;
  identity_address: string;
  staking_address: string;
  collection_address: string;
  endpoint_url: string;
  gateway_ca_cert?: string;
  /** @deprecated Use identity_address. */
  address: string;
}

/** Normalize a raw register result, filling v0.2.0 fields from legacy address if needed. */
export function normalizeRegisterResult(
  raw: Record<string, unknown>,
): RegisterResult {
  const addr = (raw.address ?? raw.identity_address ?? "") as string;
  return {
    ...raw,
    identity_address: (raw.identity_address ?? addr) as string,
    staking_address: (raw.staking_address ?? addr) as string,
    collection_address: (raw.collection_address ?? addr) as string,
    address: addr,
  } as RegisterResult;
}

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------

/** Checkout session returned by `POST /billing/checkout`. */
export interface CheckoutSession {
  checkout_url: string;
}

/** Reissued API key returned by `POST /billing/reissue`. */
export interface BillingReissueResult {
  new_api_key: string;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

/** Single data transfer record. */
export interface Transfer {
  request_id: string;
  bytes: number;
  method: string;
  target_host: string;
  created_at: string;
}

/** Paginated transfer list from `GET /dashboard/transfers`. */
export interface TransferPage {
  page: number;
  total_pages: number;
  total_bytes: number;
  transfers: Transfer[];
}

// ---------------------------------------------------------------------------
// Credit line (v0.2.0)
// ---------------------------------------------------------------------------

/** Credit line status from `GET /credit-lines/{address}`. */
export interface CreditLineStatus {
  address: string;
  credit_limit: number;
  used: number;
  available: number;
  status: "active" | "suspended" | "pending";
  foundation_managed: boolean;
}

/** Vouching signature proving identity wallet vouches for staking wallet. */
export interface VouchingSignature {
  identity_address: string;
  staking_address: string;
  signature: string;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// Proxy response
// ---------------------------------------------------------------------------

/**
 * Thin wrapper around `Response` with SpaceRouter metadata.
 *
 * Exposes {@link nodeId} and {@link requestId} from response headers and
 * delegates common properties to the underlying fetch `Response`.
 *
 * For HTTPS target URLs (the typical case) the gateway sends
 * ``X-SpaceRouter-Node`` on the proxy CONNECT 200 response, which undici
 * normally drops before user code sees it. The SDK's
 * ``CapturingProxyAgent`` snapshots those CONNECT headers and the
 * client passes them in via the optional ``metadata`` argument so
 * ``nodeId`` works for HTTPS too. For plain-HTTP targets the gateway
 * also injects the same header into the inner response, so the
 * fallback path below handles that case directly off the fetch
 * response.
 */
export interface ProxyResponseMetadata {
  /** ID of the Provider that served this request (CONNECT capture). */
  nodeId?: string;
  /** X-SpaceRouter-Request-Id from the CONNECT response. */
  requestId?: string;
  /** "home" or "fallback" — gateway's routing decision tag. */
  routingTag?: string;
}

export class ProxyResponse {
  private readonly _response: Response;
  private readonly _metadata: ProxyResponseMetadata;

  constructor(response: Response, metadata?: ProxyResponseMetadata) {
    this._response = response;
    this._metadata = metadata ?? {};
  }

  /** Unique request ID for tracing (`X-SpaceRouter-Request-Id`). */
  get requestId(): string | undefined {
    // CONNECT-captured value first (set for HTTPS targets); fall back to
    // the inner response header (HTTP targets — gateway injects the same
    // X-SpaceRouter-Request-Id into the inner response stream).
    return (
      this._metadata.requestId
      ?? this._response.headers.get("x-spacerouter-request-id")
      ?? undefined
    );
  }

  /** ID of the Provider that served this request (`X-SpaceRouter-Node`). */
  get nodeId(): string | undefined {
    // Same precedence as requestId: CONNECT capture wins for HTTPS;
    // HTTP target requests fall back to the inner response header
    // (gateway injects ``X-SpaceRouter-Node`` for one-shot HTTP).
    return (
      this._metadata.nodeId
      ?? this._response.headers.get("x-spacerouter-node")
      ?? undefined
    );
  }

  /** Gateway's routing tag — `"home"` for normal nodes, `"fallback"` otherwise. */
  get routingTag(): string | undefined {
    return (
      this._metadata.routingTag
      ?? this._response.headers.get("x-spacerouter-routing")
      ?? undefined
    );
  }

  /** HTTP status code. */
  get status(): number {
    return this._response.status;
  }

  /** HTTP status text. */
  get statusText(): string {
    return this._response.statusText;
  }

  /** Whether the response status is 2xx. */
  get ok(): boolean {
    return this._response.ok;
  }

  /** Response headers. */
  get headers(): Headers {
    return this._response.headers;
  }

  /** Whether the body has been consumed. */
  get bodyUsed(): boolean {
    return this._response.bodyUsed;
  }

  /** Parse response body as JSON. */
  async json(): Promise<unknown> {
    return this._response.json();
  }

  /** Read response body as text. */
  async text(): Promise<string> {
    return this._response.text();
  }

  /** Read response body as ArrayBuffer. */
  async arrayBuffer(): Promise<ArrayBuffer> {
    return this._response.arrayBuffer();
  }

  /** Read response body as Blob. */
  async blob(): Promise<Blob> {
    return this._response.blob();
  }

  /** Access the underlying fetch Response. */
  get raw(): Response {
    return this._response;
  }

  toString(): string {
    return `ProxyResponse [${this._response.status}]`;
  }
}
