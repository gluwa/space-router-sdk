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
  CreditLineStatus,
  Node,
  NodeStatus,
  RegisterChallenge,
  RegisterResult,
  SpaceRouterAdminOptions,
  TransferPage,
} from "./models.js";
import { normalizeNode, normalizeRegisterResult } from "./models.js";

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

  // -- Node management ------------------------------------------------------

  /**
   * Register a new proxy node.
   *
   * v0.2.0 accepts separate wallet addresses for identity, staking, and
   * collection roles.  The legacy `wallet_address` parameter is still
   * accepted for backward compatibility.
   */
  async registerNode(params: {
    endpoint_url: string;
    identity_address?: string;
    staking_address?: string;
    collection_address?: string;
    vouching_signature?: string;
    vouching_timestamp?: number;
    label?: string;
    connectivity_type?: string;
    /** @deprecated Use identity_address + staking_address + collection_address. */
    wallet_address?: string;
  }): Promise<Node> {
    const body: Record<string, unknown> = { ...params };
    if (params.wallet_address && !params.identity_address) {
      body.identity_address = params.wallet_address;
      body.staking_address ??= params.wallet_address;
      body.collection_address ??= params.wallet_address;
    }

    const response = await this._fetch("/nodes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to register node: ${response.status} ${response.statusText}`,
      );
    }

    return normalizeNode(await response.json() as Record<string, unknown>);
  }

  /**
   * Register a node using an identity key.
   *
   * Derives the identity address and creates the vouching signature
   * automatically.
   */
  async registerNodeWithIdentity(params: {
    privateKey: `0x${string}`;
    endpointUrl: string;
    stakingAddress: string;
    collectionAddress?: string;
    label?: string;
    connectivityType?: string;
  }): Promise<Node> {
    const { getAddress, createVouchingSignature } = await import(
      "./identity.js"
    );
    const identityAddress = getAddress(params.privateKey);
    const collectionAddress = params.collectionAddress ?? identityAddress;
    const { signature, timestamp } = await createVouchingSignature(
      params.privateKey,
      params.stakingAddress,
    );
    return this.registerNode({
      endpoint_url: params.endpointUrl,
      identity_address: identityAddress,
      staking_address: params.stakingAddress,
      collection_address: collectionAddress,
      vouching_signature: signature,
      vouching_timestamp: timestamp,
      label: params.label,
      connectivity_type: params.connectivityType,
    });
  }

  /** List all registered nodes. */
  async listNodes(): Promise<Node[]> {
    const response = await this._fetch("/nodes", { method: "GET" });

    if (!response.ok) {
      throw new Error(
        `Failed to list nodes: ${response.status} ${response.statusText}`,
      );
    }

    const raw = (await response.json()) as Record<string, unknown>[];
    return raw.map(normalizeNode);
  }

  /**
   * Update a node's operational status (offline or draining only).
   * Requires a signed request proving node identity ownership.
   */
  async updateNodeStatus(
    nodeId: string,
    status: NodeStatus,
    auth: {
      identityAddress: string;
      signature: string;
      timestamp: number;
      /** @deprecated Use identityAddress. */
      walletAddress?: string;
    },
  ): Promise<void> {
    const addr = auth.identityAddress ?? auth.walletAddress;
    const response = await this._fetch(`/nodes/${nodeId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        identity_address: addr,
        wallet_address: addr,
        signature: auth.signature,
        timestamp: auth.timestamp,
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to update node status: ${response.status} ${response.statusText}`,
      );
    }
  }

  /**
   * Request a health probe for an offline node.
   * Requires a signed request proving node identity ownership.
   */
  async requestProbe(
    nodeId: string,
    auth: {
      identityAddress: string;
      signature: string;
      timestamp: number;
      /** @deprecated Use identityAddress. */
      walletAddress?: string;
    },
  ): Promise<void> {
    const addr = auth.identityAddress ?? auth.walletAddress;
    const response = await this._fetch(`/nodes/${nodeId}/request-probe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identity_address: addr,
        wallet_address: addr,
        signature: auth.signature,
        timestamp: auth.timestamp,
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Failed to request probe: ${response.status} ${response.statusText}`,
      );
    }
  }

  /**
   * Delete a registered node.
   * Requires a signed request proving node identity ownership.
   */
  async deleteNode(
    nodeId: string,
    auth: {
      identityAddress: string;
      signature: string;
      timestamp: number;
      /** @deprecated Use identityAddress. */
      walletAddress?: string;
    },
  ): Promise<void> {
    const addr = auth.identityAddress ?? auth.walletAddress;
    const response = await this._fetch(`/nodes/${nodeId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        identity_address: addr,
        wallet_address: addr,
        signature: auth.signature,
        timestamp: auth.timestamp,
      }),
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

    return normalizeRegisterResult(
      (await response.json()) as Record<string, unknown>,
    );
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

  // -- Credit lines (v0.2.0) ------------------------------------------------

  /** Query credit line status for an address. */
  async getCreditLine(address: string): Promise<CreditLineStatus> {
    const response = await this._fetch(`/credit-lines/${address}`, {
      method: "GET",
    });

    if (!response.ok) {
      throw new Error(
        `Failed to get credit line: ${response.status} ${response.statusText}`,
      );
    }

    return (await response.json()) as CreditLineStatus;
  }

  // -- Dashboard ------------------------------------------------------------

  /**
   * Get paginated data transfer history.
   *
   * Accepts `identity_address` (v0.2.0) or the deprecated `wallet_address`.
   */
  async getTransfers(params: {
    identity_address?: string;
    /** @deprecated Use identity_address. */
    wallet_address?: string;
    page?: number;
    page_size?: number;
  }): Promise<TransferPage> {
    const addr = params.identity_address ?? params.wallet_address;
    if (!addr) throw new Error("identity_address (or wallet_address) is required");

    const query = new URLSearchParams({ wallet_address: addr });
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
