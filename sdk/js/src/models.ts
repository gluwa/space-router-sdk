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
  /** Proxy gateway URL. Default: `"https://gateway.spacerouter.org:8080"` */
  gatewayUrl?: string;
  /** Proxy protocol. Default: `"http"` */
  protocol?: "http" | "socks5";
  /** Region filter — 2-letter country code (ISO 3166-1 alpha-2, e.g. "US"). */
  region?: string;
  /** IP type filter — restrict to a specific address type. */
  ipType?: IpType;
  /** Request timeout in milliseconds. Default: `30_000` */
  timeout?: number;
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

/** Proxy node returned by `GET /nodes` and `POST /nodes`. */
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
  wallet_address: string;
  created_at: string;
  gateway_ca_cert?: string;
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
  address: string;
  endpoint_url: string;
  gateway_ca_cert?: string;
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

/**
 * Thin wrapper around `Response` with SpaceRouter metadata.
 *
 * Exposes {@link nodeId} and {@link requestId} from response headers and
 * delegates common properties to the underlying fetch `Response`.
 */
export class ProxyResponse {
  private readonly _response: Response;

  constructor(response: Response) {
    this._response = response;
  }

  /** Unique request ID for tracing (`X-SpaceRouter-Request-Id`). */
  get requestId(): string | undefined {
    return this._response.headers.get("x-spacerouter-request-id") ?? undefined;
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
