/**
 * SpaceRouter proxy client.
 *
 * Routes HTTP requests through the Space Router residential proxy network
 * via HTTP or SOCKS5.
 */

import { SocksProxyAgent } from "socks-proxy-agent";
import {
  AuthenticationError,
  NoNodesAvailableError,
  QuotaExceededError,
  RateLimitError,
  SpaceRouterError,
  UpstreamError,
} from "./errors.js";
import type { IpType, SpaceRouterOptions } from "./models.js";
import { ProxyResponse } from "./models.js";
import type { SpaceRouterSPACE } from "./payment/spacecoin.js";
import { CapturingProxyAgent } from "./proxyAgent.js";

const DEFAULT_HTTP_GATEWAY = "https://gateway.spacerouter.org";
const DEFAULT_TIMEOUT = 30_000;
const REGION_RE = /^[A-Z]{2}$/;

/** Throw if region is not a 2-letter country code. */
function validateRegion(region: string): void {
  if (!REGION_RE.test(region)) {
    throw new Error(
      `region must be a 2-letter country code (ISO 3166-1 alpha-2), got "${region}"`,
    );
  }
}

/** Options passed through to individual requests. */
export interface RequestOptions {
  headers?: Record<string, string>;
  body?: BodyInit;
  signal?: AbortSignal;
  /**
   * v1.5 escrow payment façade.  When set, the client fetches a fresh
   * challenge per request and injects the four `X-SpaceRouter-*` payment
   * headers into the outgoing request.  Headers always take precedence over
   * caller-supplied entries with the same name.
   */
  payment?: SpaceRouterSPACE;
  /**
   * v1.5 auto-settle: after a request, call `payment.syncReceipts()`.
   * Errors are warn-logged unless `payment.strict` is true.
   * Has no effect unless `payment` is also set.
   */
  autoSettle?: boolean;
}

/**
 * Build a proxy agent for the given protocol.
 * - HTTPS/HTTP: undici ProxyAgent preserving the gateway scheme
 * - SOCKS5: socks-proxy-agent with `socks5://apiKey:@host:port`
 */
function buildAgent(
  apiKey: string,
  gatewayUrl: string,
  protocol: "http" | "socks5",
  region?: string,
  ipType?: IpType,
  verify: boolean = true,
): CapturingProxyAgent | SocksProxyAgent {
  const parsed = new URL(gatewayUrl);
  const host = parsed.hostname || "localhost";
  const scheme = parsed.protocol.replace(":", "") || "https";

  if (protocol === "socks5") {
    const port = parsed.port || "1080";
    const socksUrl = `socks5://${apiKey}:@${host}:${port}`;
    // socks-proxy-agent's TLS verification for the inner request is
    // controlled by Node's https module / `NODE_TLS_REJECT_UNAUTHORIZED`,
    // not a constructor option that propagates cleanly here. Document the
    // workaround in models.ts/README; do not try to wire `verify` into
    // SOCKS5 — it would be a no-op and misleading.
    return new SocksProxyAgent(socksUrl);
  }

  const port = parsed.port || (scheme === "https" ? "443" : "8080");
  const proxyUrl = `${scheme}://${host}:${port}`;
  // undici sends `proxy-authorization` (lowercase) but some proxy servers
  // require title-case `Proxy-Authorization`.  Use explicit headers instead
  // of the `token` option to control the casing.
  // Region/ipType MUST land on the proxy CONNECT (gateway can't read inside
  // the inner TLS tunnel), so we stamp them onto the agent's headers map.
  const proxyHeaders: Record<string, string> = {
    "Proxy-Authorization": `Basic ${Buffer.from(`${apiKey}:`).toString("base64")}`,
  };
  if (region) proxyHeaders["X-SpaceRouter-Region"] = region;
  if (ipType) proxyHeaders["X-SpaceRouter-IP-Type"] = ipType;

  // `verify: false` toggles TLS cert verification for both the gateway
  // (proxyTls) and the inner CONNECT-tunnelled request (requestTls).
  // The reported repro was SELF_SIGNED_CERT_IN_CHAIN on the gateway hop,
  // but disabling only proxyTls leaves the inner TLS context strict and
  // can re-trigger the same failure mode for self-signed inner targets
  // (e.g. when the test gateway speaks TLS twice).
  const tlsOpts = verify ? undefined : { rejectUnauthorized: false };

  // CapturingProxyAgent extends ProxyAgent and snapshots the CONNECT
  // response headers (X-SpaceRouter-Node etc.) so they survive the hop
  // through undici's fetch — ProxyResponse reads them back via the
  // `metadata` argument set by the request layer below.
  return new CapturingProxyAgent({
    uri: proxyUrl,
    headers: proxyHeaders,
    ...(tlsOpts ? { proxyTls: tlsOpts, requestTls: tlsOpts } : {}),
  });
}

/** Check for proxy-layer errors and throw typed exceptions. */
async function checkProxyErrors(response: Response): Promise<void> {
  const requestId =
    response.headers.get("x-spacerouter-request-id") ?? undefined;

  if (response.status === 402) {
    let limitBytes = 0;
    let usedBytes = 0;
    let message = "Monthly data transfer limit exceeded";
    try {
      const body = (await response.clone().json()) as Record<string, unknown>;
      if (typeof body.message === "string") message = body.message;
      if (typeof body.limit_bytes === "number") limitBytes = body.limit_bytes;
      if (typeof body.used_bytes === "number") usedBytes = body.used_bytes;
    } catch {
      // JSON parse failure — use defaults
    }
    throw new QuotaExceededError(message, {
      limitBytes,
      usedBytes,
      statusCode: 402,
      requestId,
    });
  }

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
    throw new UpstreamError("Target unreachable via residential node", {
      statusCode: 502,
      requestId,
    });
  }

  if (response.status === 503) {
    // Any 503 from the proxy chain — gateway-rejected, upstream timeout,
    // empty body, etc. — is mapped to NoNodesAvailableError so callers
    // get a typed signal instead of crashing on response.json().
    let message = "No residential nodes currently available";
    try {
      const body = (await response.clone().json()) as Record<string, unknown>;
      if (typeof body.message === "string" && body.message.length > 0) {
        message = body.message;
      }
    } catch {
      // JSON parse failure — fall through with the generic message.
    }
    throw new NoNodesAvailableError(message, { statusCode: 503, requestId });
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
/**
 * Options for the {@link SpaceRouter} constructor — superset of
 * {@link SpaceRouterOptions} that also accepts the v1.5 payment façade
 * and an autoSettle flag.  Setting them here makes every request paid
 * by default; callers can still override per-call via {@link RequestOptions}.
 */
export interface SpaceRouterClientOptions extends SpaceRouterOptions {
  /** v1.5 escrow payment façade. See {@link RequestOptions.payment}. */
  payment?: SpaceRouterSPACE;
  /** v1.5 auto-settle. See {@link RequestOptions.autoSettle}. */
  autoSettle?: boolean;
}

export class SpaceRouter {
  private readonly _apiKey: string;
  private readonly _gatewayUrl: string;
  private readonly _protocol: "http" | "socks5";
  private readonly _region: string | undefined;
  private readonly _ipType: IpType | undefined;
  private readonly _timeout: number;
  private readonly _verify: boolean;
  private readonly _agent: CapturingProxyAgent | SocksProxyAgent;
  private readonly _payment: SpaceRouterSPACE | undefined;
  private readonly _autoSettle: boolean;

  constructor(apiKey: string, options?: SpaceRouterClientOptions) {
    this._apiKey = apiKey;
    this._gatewayUrl = options?.gatewayUrl ?? DEFAULT_HTTP_GATEWAY;
    this._protocol = options?.protocol ?? "http";
    this._region = options?.region;
    this._ipType = options?.ipType;
    if (this._region) validateRegion(this._region);
    this._timeout = options?.timeout ?? DEFAULT_TIMEOUT;
    this._verify = options?.verify ?? true;
    this._agent = buildAgent(
      apiKey,
      this._gatewayUrl,
      this._protocol,
      this._region,
      this._ipType,
      this._verify,
    );
    this._payment = options?.payment;
    this._autoSettle = options?.autoSettle ?? false;
  }

  // -- HTTP methods ---------------------------------------------------------

  /** Send a request through the SpaceRouter proxy. */
  async request(
    method: string,
    url: string,
    options?: RequestOptions,
  ): Promise<ProxyResponse> {
    // User-supplied inner-request headers — these ride inside the TLS tunnel
    // and are NOT visible to the gateway. Routing/payment headers go on the
    // proxy CONNECT below.
    const headers: Record<string, string> = { ...options?.headers };

    // v1.5 payment header injection — fetch fresh challenge per request.
    // Payment headers MUST land on the proxy CONNECT (not on the inner
    // TLS-tunnelled request) so the gateway can read them. We achieve
    // this by building a per-request ProxyAgent with the payment
    // headers stamped onto its connect-time headers map. The shared
    // long-lived `_agent` is only used for non-paid requests.
    //
    // `payment` and `autoSettle` may be supplied either at construction
    // time (the documented happy path) or per-call via RequestOptions.
    // Per-call overrides take precedence; otherwise we fall back to the
    // values stored on the client.
    const payment = options?.payment ?? this._payment;
    const autoSettle = options?.autoSettle ?? this._autoSettle;
    let dispatcher = this._agent;
    if (payment) {
      const challenge = await payment.requestChallenge();
      const paymentHeaders = await payment.buildAuthHeaders(challenge);
      const parsed = new URL(this._gatewayUrl);
      const scheme = parsed.protocol.replace(":", "") || "https";
      const port = parsed.port || (scheme === "https" ? "443" : "8080");
      const proxyUrl = `${scheme}://${parsed.hostname}:${port}`;
      const connectHeaders: Record<string, string> = {
        "Proxy-Authorization": `Basic ${Buffer.from(`${this._apiKey}:`).toString("base64")}`,
        ...paymentHeaders,
      };
      if (this._region) connectHeaders["X-SpaceRouter-Region"] = this._region;
      if (this._ipType) connectHeaders["X-SpaceRouter-IP-Type"] = this._ipType;
      const tlsOpts = this._verify
        ? undefined
        : { rejectUnauthorized: false };
      dispatcher = new CapturingProxyAgent({
        uri: proxyUrl,
        headers: connectHeaders,
        ...(tlsOpts ? { proxyTls: tlsOpts, requestTls: tlsOpts } : {}),
      });
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
        dispatcher,
      });

      await checkProxyErrors(response);
      // For HTTPS targets the gateway emits X-SpaceRouter-Node / -Request-Id
      // on the CONNECT 200 response. undici doesn't expose CONNECT headers
      // to fetch's Response object, so we read them off the dispatcher
      // instead — CapturingProxyAgent snapshotted them when the tunnel
      // was established. SOCKS5 has no CONNECT header concept; metadata
      // stays empty and ProxyResponse falls back to the inner-response
      // header (HTTP target) or undefined.
      const metadata =
        dispatcher instanceof CapturingProxyAgent
          ? dispatcher.capturedMetadata()
          : undefined;
      const proxyResponse = new ProxyResponse(response, metadata);

      // NOTE: do NOT close the per-request dispatcher here even though
      // we built it just for this call. fetch() returns when HEADERS
      // arrive; the body stream still needs the underlying connection
      // open while the caller reads .arrayBuffer() / .json() / .text().
      // Closing here aborted body reads on large responses (E3 1MB
      // failed every time). The dispatcher is GC-collected after the
      // response is consumed; leaking it for the request's lifetime
      // is the correct trade-off vs. truncating bodies.

      if (autoSettle && payment) {
        try {
          await payment.syncReceipts();
        } catch (settleErr) {
          if (payment.strict) {
            throw settleErr;
          }
          // eslint-disable-next-line no-console
          console.warn(
            `[spacerouter] autoSettle failed (non-strict, swallowed): ${
              settleErr instanceof Error ? settleErr.message : String(settleErr)
            }`,
          );
        }
      }

      return proxyResponse;
    } catch (err) {
      if (err instanceof SpaceRouterError) throw err;

      // undici converts a 407 during HTTPS CONNECT tunnel setup into a
      // TypeError("fetch failed") instead of returning a Response object.
      // Detect this and surface the proper AuthenticationError.
      if (err instanceof TypeError && err.message === "fetch failed") {
        const cause = (err as { cause?: Error }).cause;
        if (cause?.message?.toLowerCase().includes("proxy authentication required")) {
          throw new AuthenticationError("Invalid or missing API key", {
            statusCode: 407,
          });
        }
        // Same pattern for CONNECT-time 503: undici's proxy-agent throws
        // RequestAbortedError("Proxy response (503) !== 200 when HTTP Tunneling")
        // before fetch can return a Response, so the response.status === 503
        // branch above never sees it. Map it to NoNodesAvailableError here.
        if (cause?.message?.includes("Proxy response (503)")) {
          throw new NoNodesAvailableError("No residential nodes currently available", {
            statusCode: 503,
          });
        }
      }
      throw err;
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
    region?: string;
    ipType?: IpType;
  }): SpaceRouter {
    // Carry over payment / autoSettle / timeout — `withRouting` is meant to
    // narrow the routing filter on an otherwise-identical client, not to
    // strip the v1.5 escrow façade.
    return new SpaceRouter(this._apiKey, {
      gatewayUrl: this._gatewayUrl,
      protocol: this._protocol,
      region: options.region,
      ipType: options.ipType,
      timeout: this._timeout,
      verify: this._verify,
      payment: this._payment,
      autoSettle: this._autoSettle,
    });
  }

  // -- Lifecycle ------------------------------------------------------------

  /** Close the underlying connection pool. */
  close(): void {
    if (
      this._agent &&
      "close" in this._agent &&
      typeof this._agent.close === "function"
    ) {
      (this._agent as CapturingProxyAgent).close();
    }
  }

  toString(): string {
    return `SpaceRouter(protocol=${this._protocol}, gateway=${this._gatewayUrl})`;
  }
}
