/**
 * `SpaceRouterSPACE` — high-level façade for v1.5 escrow-payment consumers.
 *
 * Bundles per-request auth (challenge + EIP-191 sig) and the Leg 1 broker
 * (`ConsumerSettlementClient`) behind a single object that the proxy
 * `SpaceRouter` client takes via `options.payment`.
 *
 * Reference: `internal-docs/v1.5-consumer-protocol.md` §4 (per-request
 * payment headers), §3 (`/auth/challenge`), §3 (Leg 1 broker).
 */

// TODO(track-c): swap stub for real export once Track C lands.
import {
  type ClientPaymentWallet,
  type EIP712Domain,
  type Receipt,
  type PaymentAuthHeaders,
  signReceipt,
} from "./_track-c-stub.js";
import { ConsumerSettlementClient } from "./consumerSettlement.js";
import { fetch as undiciFetch } from "undici";

export interface SpaceRouterSPACEOptions {
  gatewayMgmtUrl: string;
  // TODO(track-c): swap stub for real ClientPaymentWallet from Track C.
  wallet: ClientPaymentWallet;
  /** Propagated to ConsumerSettlementClient.submitSignatures. */
  strict?: boolean;
}

export class SpaceRouterSPACE {
  private readonly _gatewayMgmtUrl: string;
  // TODO(track-c): swap stub for real ClientPaymentWallet from Track C.
  private readonly _wallet: ClientPaymentWallet;
  private readonly _strict: boolean;
  private _settlement?: ConsumerSettlementClient;

  constructor(options: SpaceRouterSPACEOptions) {
    this._gatewayMgmtUrl = options.gatewayMgmtUrl.replace(/\/+$/, "");
    this._wallet = options.wallet;
    this._strict = options.strict ?? false;
  }

  /** True if strict-mode settlement is enabled (proxy autoSettle re-throws). */
  get strict(): boolean {
    return this._strict;
  }

  /**
   * Fetch a single-use challenge from `GET /auth/challenge`.  Per §4, SDKs
   * MUST fetch a fresh challenge per request.
   */
  async requestChallenge(): Promise<string> {
    const url = `${this._gatewayMgmtUrl}/auth/challenge`;
    const resp = await undiciFetch(url, { method: "GET" });
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(
        `GET /auth/challenge failed: HTTP ${resp.status} — ${body}`,
      );
    }
    const parsed = (await resp.json()) as { challenge?: unknown };
    if (typeof parsed.challenge !== "string" || parsed.challenge.length === 0) {
      throw new Error(
        `GET /auth/challenge: missing/invalid challenge field in response`,
      );
    }
    return parsed.challenge;
  }

  /** Build the four `X-SpaceRouter-*` per-request payment headers. */
  async buildAuthHeaders(challenge: string): Promise<PaymentAuthHeaders> {
    return this._wallet.buildAuthHeaders(challenge);
  }

  /**
   * Validate a Receipt struct's shape.  Real Track C may go further
   * (e.g. recompute signer for cross-checks); the stub-friendly version
   * just enforces the bigint invariants from §2/§8.
   */
  validateReceipt(receipt: Receipt, _domain: EIP712Domain): void {
    if (typeof receipt.dataAmount !== "bigint") {
      throw new Error("validateReceipt: dataAmount must be bigint");
    }
    if (typeof receipt.totalPrice !== "bigint") {
      throw new Error("validateReceipt: totalPrice must be bigint");
    }
    if (receipt.dataAmount < 0n || receipt.totalPrice < 0n) {
      throw new Error("validateReceipt: amounts must be non-negative");
    }
    if (!receipt.requestUUID) {
      throw new Error("validateReceipt: missing requestUUID");
    }
    if (!/^0x[0-9a-fA-F]{64}$/.test(receipt.nodeAddress)) {
      throw new Error("validateReceipt: nodeAddress must be 32-byte hex");
    }
  }

  /** Validate-then-sign convenience wrapper. */
  async signReceiptAfterValidation(
    receipt: Receipt,
    domain: EIP712Domain,
  ): Promise<`0x${string}`> {
    this.validateReceipt(receipt, domain);
    // TODO(track-c): private key isn't directly accessible on the real wallet;
    // keep the wallet.signReceipt path canonical. The standalone signReceipt is
    // re-exported for parity with the Python SDK.
    return this._wallet.signReceipt(receipt, domain);
  }

  /** Fetch + sign + submit pending Leg 1 receipts; propagates `strict`. */
  async syncReceipts(
    limit?: number,
  ): Promise<{
    accepted: string[];
    rejected: Array<{ requestUuid: string; reason: string }>;
  }> {
    if (!this._settlement) {
      this._settlement = new ConsumerSettlementClient({
        gatewayMgmtUrl: this._gatewayMgmtUrl,
        wallet: this._wallet,
      });
    }
    return this._settlement.syncReceipts(limit, { strict: this._strict });
  }
}

// Re-export the standalone signReceipt for callers that want low-level access
// without going through a wallet object (e.g. backend signing services).
export { signReceipt };
