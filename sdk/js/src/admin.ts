/**
 * Admin client for the Space Router Coordination API.
 *
 * Manages API keys via the Coordination API (`/api-keys` endpoints).
 */

import type { ApiKey, ApiKeyInfo, SpaceRouterAdminOptions } from "./models.js";

const DEFAULT_COORDINATION_URL = "https://coordination.spacerouter.org";
const DEFAULT_TIMEOUT = 10_000;

/**
 * Admin client for the Coordination API.
 *
 * @example
 * ```ts
 * const admin = new SpaceRouterAdmin();
 * const key = await admin.createApiKey("my-agent");
 * console.log(key.api_key); // sr_live_...
 * ```
 */
export class SpaceRouterAdmin {
  private readonly _baseUrl: string;
  private readonly _timeout: number;

  constructor(baseUrl?: string, options?: SpaceRouterAdminOptions) {
    this._baseUrl = (baseUrl ?? DEFAULT_COORDINATION_URL).replace(/\/+$/, "");
    this._timeout = options?.timeout ?? DEFAULT_TIMEOUT;
  }

  /**
   * Create a new API key.
   * The raw key value is **only** available in the returned object.
   */
  async createApiKey(
    name: string,
    options?: { rateLimitRpm?: number },
  ): Promise<ApiKey> {
    const response = await this._fetch("/api-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        rate_limit_rpm: options?.rateLimitRpm ?? 60,
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to create API key: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as ApiKey;
  }

  /** List all API keys (raw key values are never returned). */
  async listApiKeys(): Promise<ApiKeyInfo[]> {
    const response = await this._fetch("/api-keys", { method: "GET" });

    if (!response.ok) {
      throw new Error(
        `Failed to list API keys: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as ApiKeyInfo[];
  }

  /** Revoke an API key (soft-delete). */
  async revokeApiKey(keyId: string): Promise<void> {
    const response = await this._fetch(`/api-keys/${keyId}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      throw new Error(
        `Failed to revoke API key: ${response.status} ${response.statusText}`,
      );
    }
  }

  /**
   * Fetch the proxy network CA certificate.
   *
   * Returns the PEM-encoded certificate, or `null` when the proxy
   * network does not require a custom CA (HTTP 503).
   */
  async fetchCaCert(): Promise<string | null> {
    const response = await this._fetch("/ca-cert", { method: "GET" });
    if (response.status === 503) return null;
    if (!response.ok) {
      throw new Error(
        `Failed to fetch CA cert: ${response.status} ${response.statusText}`,
      );
    }
    return response.text();
  }

  /** Close — no-op, included for API symmetry with SpaceRouter. */
  close(): void {
    // No persistent connections to clean up with fetch
  }

  private async _fetch(path: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this._timeout);

    try {
      return await fetch(`${this._baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }
}
