/** IP type for routing preferences. */
export type IpType = "residential" | "mobile" | "datacenter" | "business";

/** Options for the {@link SpaceRouter} constructor. */
export interface SpaceRouterOptions {
  /** Proxy gateway URL. Default: `"https://gateway.spacerouter.org:8080"` */
  gatewayUrl?: string;
  /** Proxy protocol. Default: `"http"` */
  protocol?: "http" | "socks5";
  /** IP type filter for node selection. */
  ipType?: IpType;
  /** Region filter for node selection (substring match). */
  region?: string;
  /** Request timeout in milliseconds. Default: `30_000` */
  timeout?: number;
  /** Coordination API URL (for auto-fetching the CA cert). */
  coordinationUrl?: string;
  /**
   * PEM-encoded CA certificate for verifying target-site TLS through the
   * proxy network.  When omitted the SDK fetches the cert from the
   * Coordination API automatically on the first request.
   */
  caCert?: string | null;
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

  /** Node that handled the request (`X-SpaceRouter-Node`). */
  get nodeId(): string | undefined {
    return this._response.headers.get("x-spacerouter-node") ?? undefined;
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
