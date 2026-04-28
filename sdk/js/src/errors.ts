/**
 * SpaceRouter SDK exceptions.
 *
 * Maps to the error codes returned by the proxy gateway:
 * - 407 proxy_auth_required  -> AuthenticationError
 * - 429 rate_limited         -> RateLimitError
 * - 502 upstream_error       -> UpstreamError
 * - 503 no_nodes_available   -> NoNodesAvailableError
 */

/** Base error for all SpaceRouter SDK errors. */
export class SpaceRouterError extends Error {
  readonly statusCode: number | undefined;
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options?: { statusCode?: number; requestId?: string },
  ) {
    super(message);
    this.name = "SpaceRouterError";
    this.statusCode = options?.statusCode;
    this.requestId = options?.requestId;
  }
}

/** 407 Proxy Authentication Required — invalid or missing API key. */
export class AuthenticationError extends SpaceRouterError {
  constructor(
    message: string,
    options?: { statusCode?: number; requestId?: string },
  ) {
    super(message, options);
    this.name = "AuthenticationError";
  }
}

/** 429 Too Many Requests — per-key rate limit exceeded. */
export class RateLimitError extends SpaceRouterError {
  readonly retryAfter: number;

  constructor(
    message: string,
    options: { retryAfter: number; statusCode?: number; requestId?: string },
  ) {
    super(message, options);
    this.name = "RateLimitError";
    this.retryAfter = options.retryAfter;
  }
}

/** 503 Service Unavailable — no residential nodes currently available. */
export class NoNodesAvailableError extends SpaceRouterError {
  constructor(
    message: string,
    options?: { statusCode?: number; requestId?: string },
  ) {
    super(message, options);
    this.name = "NoNodesAvailableError";
  }
}

/** 402 Payment Required — monthly data transfer limit exceeded. */
export class QuotaExceededError extends SpaceRouterError {
  readonly limitBytes: number;
  readonly usedBytes: number;

  constructor(
    message: string,
    options: {
      limitBytes: number;
      usedBytes: number;
      statusCode?: number;
      requestId?: string;
    },
  ) {
    super(message, options);
    this.name = "QuotaExceededError";
    this.limitBytes = options.limitBytes;
    this.usedBytes = options.usedBytes;
  }
}

/** 502 Bad Gateway — target unreachable via residential node. */
export class UpstreamError extends SpaceRouterError {
  constructor(
    message: string,
    options?: { statusCode?: number; requestId?: string },
  ) {
    super(message, options);
    this.name = "UpstreamError";
  }
}
