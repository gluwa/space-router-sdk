/**
 * SpaceRouter proxy client.
 *
 * Routes HTTP requests through the Space Router residential proxy network
 * via HTTP or SOCKS5.
 */

import { ProxyAgent } from "undici";
import { SocksProxyAgent } from "socks-proxy-agent";
import {
  AuthenticationError,
  NoNodesAvailableError,
  RateLimitError,
  UpstreamError,
} from "./errors.js";
import type { IpType, SpaceRouterOptions } from "./models.js";
import { ProxyResponse } from "./models.js";

const DEFAULT_HTTP_GATEWAY = "http://gateway.spacerouter.org:8080";
const DEFAULT_TIMEOUT = 30_000;

/** Options passed through to individual requests. */
export interface RequestOptions {
  headers?: Record<string, string>;
  body?: BodyInit;
  signal?: AbortSignal;
}

/**
 * Build a proxy agent for the given protocol.
 * - HTTP: undici ProxyAgent with `http://apiKey:@host:port`
 * - SOCKS5: socks-proxy-agent with `socks5://apiKey:@host:port`
 */
function buildAgent(
  apiKey: string,
  gatewayUrl: string,
  protocol: "http" | "socks5",
): ProxyAgent | SocksProxyAgent {
  const parsed = new URL(gatewayUrl);
  const host = parsed.hostname || "localhost";

  if (protocol === "socks5") {
    const port = parsed.port || "1080";
    const socksUrl = `socks5://${apiKey}:@${host}:${port}`;
    return new SocksProxyAgent(socksUrl);
  }

  const port = parsed.port || "8080";
  const proxyUrl = `http://${apiKey}:@${host}:${port}`;
  return new ProxyAgent(proxyUrl);
}

/** Check for proxy-layer errors and throw typed exceptions. */
async function checkProxyErrors(response: Response): Promise<void> {
  const requestId =
    response.headers.get("x-spacerouter-request-id") ?? undefined;

  if (response.status === 407) {
    throw new AuthenticationError("Invalid or missing API key", {
      statusCode: 407,
      requestId,
    });
  }

  if (response.status === 429) {
    const retryAfter = parseInt(
      response.headers.get("retry-after") ?? "60",
      10,
    );
    throw new RateLimitError("Rate limit exceeded", {
      retryAfter,
      statusCode: 429,
      requestId,
    });
  }

  if (response.status === 502) {
    const nodeId =
      response.headers.get("x-spacerouter-node") ?? undefined;
    throw new UpstreamError("Target unreachable via residential node", {
      nodeId,
      statusCode: 502,
      requestId,
    });
  }

  if (response.status === 503) {
    try {
      const body = (await response.clone().json()) as Record<string, unknown>;
      if (body.error === "no_nodes_available") {
        throw new NoNodesAvailableError(
          "No residential nodes currently available",
          { statusCode: 503, requestId },
        );
      }
    } catch (e) {
      if (e instanceof NoNodesAvailableError) throw e;
      // JSON parse failure — not a SpaceRouter error, pass through
    }
  }
}

/**
 * SpaceRouter proxy client.
 *
 * @example
 * ```ts
 * const client = new SpaceRouter("sr_live_xxx");
 * const resp = await client.get("https://example.com");
 * console.log(resp.status, resp.nodeId);
 * client.close();
 * ```
 */
export class SpaceRouter {
  private readonly _apiKey: string;
  private readonly _gatewayUrl: string;
  private readonly _protocol: "http" | "socks5";
  private readonly _ipType: IpType | undefined;
  private readonly _region: string | undefined;
  private readonly _timeout: number;
  private readonly _agent: ProxyAgent | SocksProxyAgent;

  constructor(apiKey: string, options?: SpaceRouterOptions) {
    this._apiKey = apiKey;
    this._gatewayUrl = options?.gatewayUrl ?? DEFAULT_HTTP_GATEWAY;
    this._protocol = options?.protocol ?? "http";
    this._ipType = options?.ipType;
    this._region = options?.region;
    this._timeout = options?.timeout ?? DEFAULT_TIMEOUT;
    this._agent = buildAgent(apiKey, this._gatewayUrl, this._protocol);
  }

  // -- HTTP methods ---------------------------------------------------------

  /** Send a request through the SpaceRouter proxy. */
  async request(
    method: string,
    url: string,
    options?: RequestOptions,
  ): Promise<ProxyResponse> {
    const headers: Record<string, string> = { ...options?.headers };

    if (this._ipType) {
      headers["X-SpaceRouter-IP-Type"] = this._ipType;
    }
    if (this._region) {
      headers["X-SpaceRouter-Region"] = this._region;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this._timeout);
    const signal = options?.signal ?? controller.signal;

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: options?.body,
        signal,
        // @ts-expect-error -- Node.js fetch dispatcher option
        dispatcher: this._agent,
      });

      await checkProxyErrors(response);
      return new ProxyResponse(response);
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async get(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("GET", url, options);
  }

  async post(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("POST", url, options);
  }

  async put(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("PUT", url, options);
  }

  async patch(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("PATCH", url, options);
  }

  async delete(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("DELETE", url, options);
  }

  async head(url: string, options?: RequestOptions): Promise<ProxyResponse> {
    return this.request("HEAD", url, options);
  }

  // -- Routing --------------------------------------------------------------

  /** Return a new client with different routing preferences. */
  withRouting(options: {
    ipType?: IpType;
    region?: string;
  }): SpaceRouter {
    return new SpaceRouter(this._apiKey, {
      gatewayUrl: this._gatewayUrl,
      protocol: this._protocol,
      ipType: options.ipType,
      region: options.region,
      timeout: this._timeout,
    });
  }

  // -- Lifecycle ------------------------------------------------------------

  /** Close the underlying connection pool. */
  close(): void {
    if ("close" in this._agent && typeof this._agent.close === "function") {
      (this._agent as ProxyAgent).close();
    }
  }

  toString(): string {
    return `SpaceRouter(protocol=${this._protocol}, gateway=${this._gatewayUrl})`;
  }
}
