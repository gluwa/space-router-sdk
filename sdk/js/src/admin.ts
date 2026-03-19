/**
 * Admin client for the Space Router Coordination API.
 *
 * Manages API keys via the Coordination API (`/api-keys` endpoints).
 */

import type {
  ApiKey,
  ApiKeyInfo,
  BillingReissueResult,
  CheckoutSession,
  Node,
  NodeStatus,
  RegisterChallenge,
  RegisterResult,
  SpaceRouterAdminOptions,
  TransferPage,
} from "./models.js";

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
    if (response.status === 404 || response.status === 503) return null;
    if (!response.ok) {
      throw new Error(
        `Failed to fetch CA cert: ${response.status} ${response.statusText}`,
      );
    }
    return response.text();
  }

  // -- Node management ------------------------------------------------------

  /** Register a new proxy node. */
  async registerNode(params: {
    endpoint_url: string;
    wallet_address: string;
    label?: string;
    connectivity_type?: string;
  }): Promise<Node> {
    const response = await this._fetch("/nodes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to register node: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as Node;
  }

  /** List all registered nodes. */
  async listNodes(): Promise<Node[]> {
    const response = await this._fetch("/nodes", { method: "GET" });

    if (!response.ok) {
      throw new Error(
        `Failed to list nodes: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as Node[];
  }

  /** Update a node's operational status. */
  async updateNodeStatus(nodeId: string, status: NodeStatus): Promise<void> {
    const response = await this._fetch(`/nodes/${nodeId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to update node status: ${response.status} ${response.statusText}`,
      );
    }
  }

  /** Delete a registered node. */
  async deleteNode(nodeId: string): Promise<void> {
    const response = await this._fetch(`/nodes/${nodeId}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      throw new Error(
        `Failed to delete node: ${response.status} ${response.statusText}`,
      );
    }
  }

  // -- Staking registration -------------------------------------------------

  /** Request a signing challenge for Creditcoin staking registration. */
  async getRegisterChallenge(address: string): Promise<RegisterChallenge> {
    const response = await this._fetch("/nodes/register/challenge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to get register challenge: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as RegisterChallenge;
  }

  /** Verify a signed nonce and register the node via staking. */
  async verifyAndRegister(params: {
    address: string;
    endpoint_url: string;
    signed_nonce: string;
    label?: string;
  }): Promise<RegisterResult> {
    const response = await this._fetch("/nodes/register/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to verify and register: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as RegisterResult;
  }

  // -- Billing --------------------------------------------------------------

  /** Create a Stripe checkout session. */
  async createCheckout(email: string): Promise<CheckoutSession> {
    const response = await this._fetch("/billing/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to create checkout: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as CheckoutSession;
  }

  /** Verify an email address with a token. */
  async verifyEmail(token: string): Promise<void> {
    const response = await this._fetch(
      `/billing/verify?token=${encodeURIComponent(token)}`,
      { method: "GET" },
    );

    if (!response.ok) {
      throw new Error(
        `Failed to verify email: ${response.status} ${response.statusText}`,
      );
    }
  }

  /** Reissue an API key using email verification. */
  async reissueApiKey(params: {
    email: string;
    token: string;
  }): Promise<BillingReissueResult> {
    const response = await this._fetch("/billing/reissue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to reissue API key: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as BillingReissueResult;
  }

  // -- Dashboard ------------------------------------------------------------

  /** Get paginated data transfer history. */
  async getTransfers(params: {
    wallet_address: string;
    page?: number;
    page_size?: number;
  }): Promise<TransferPage> {
    const query = new URLSearchParams({
      wallet_address: params.wallet_address,
    });
    if (params.page != null) query.set("page", String(params.page));
    if (params.page_size != null)
      query.set("page_size", String(params.page_size));

    const response = await this._fetch(
      `/dashboard/transfers?${query.toString()}`,
      { method: "GET" },
    );

    if (!response.ok) {
      throw new Error(
        `Failed to get transfers: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as TransferPage;
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
