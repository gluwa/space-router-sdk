/**
 * SpaceRouterSPACE — high-level client for SPACE-paid proxy usage (v0.2.3).
 *
 * Handles the full flow:
 * 1. Request challenge from gateway
 * 2. Sign challenge with identity key
 * 3. Build auth headers
 * 4. Make proxied request
 * 5. Exchange and sign receipt
 *
 * @module spacerouterSpace
 */

import type { Address, Hex } from "viem";

import { ClientWallet, type ClientWalletOptions } from "./payment/clientWallet.js";
import {
  ReceiptValidator,
  type ReceiptData,
  type ReceiptValidatorOptions,
  type ValidationResult,
} from "./payment/receiptValidator.js";
import type { Receipt } from "./escrow.js";

export interface SpaceRouterSPACEOptions {
  /** Gateway management API URL (e.g., http://gateway.spacerouter.io:8081) */
  gatewayUrl: string;
  /** Gateway proxy URL (e.g., http://gateway.spacerouter.io:8080) */
  proxyUrl: string;
  /** Client wallet private key */
  privateKey: Hex;
  /** Chain ID for EIP-712 domain (default: Creditcoin 102031) */
  chainId?: number;
  /** Escrow contract address for EIP-712 domain */
  escrowContract?: Address;
  /** Maximum acceptable rate per GB in wei (for receipt validation) */
  maxRatePerGbWei?: bigint;
}

export interface ChallengeResponse {
  challenge: string;
  ttl_seconds: number;
  message_format: string;
}

export interface AuthHeaders {
  "X-SpaceRouter-Payment-Address": string;
  "X-SpaceRouter-Identity-Address": string;
  "X-SpaceRouter-Challenge-Signature": string;
  "X-SpaceRouter-Challenge": string;
}

/**
 * Client for SPACE-paid proxy requests through Space Router.
 */
export class SpaceRouterSPACE {
  private gatewayUrl: string;
  private proxyUrl: string;
  private wallet: ClientWallet;
  private validator: ReceiptValidator;

  constructor(options: SpaceRouterSPACEOptions) {
    this.gatewayUrl = options.gatewayUrl.replace(/\/$/, "");
    this.proxyUrl = options.proxyUrl.replace(/\/$/, "");

    this.wallet = new ClientWallet({
      privateKey: options.privateKey,
      chainId: options.chainId,
      escrowContract: options.escrowContract,
    });

    this.validator = new ReceiptValidator({
      clientAddress: this.wallet.address,
      maxRatePerGbWei: options.maxRatePerGbWei,
    });
  }

  /** Client payment address. */
  get address(): string {
    return this.wallet.address;
  }

  /**
   * Request an authentication challenge from the gateway.
   *
   * @returns The challenge string.
   */
  async requestChallenge(): Promise<string> {
    const response = await fetch(`${this.gatewayUrl}/auth/challenge`);
    if (!response.ok) {
      throw new Error(`Challenge request failed: ${response.status} ${response.statusText}`);
    }
    const data: ChallengeResponse = await response.json();
    return data.challenge;
  }

  /**
   * Build authentication headers for a SPACE-paid proxy request.
   *
   * @param challenge - Challenge obtained from `requestChallenge()`.
   * @returns Headers to include in the proxy request.
   */
  async buildAuthHeaders(challenge: string): Promise<AuthHeaders> {
    const signature = await this.wallet.signChallenge(challenge);
    return {
      "X-SpaceRouter-Payment-Address": this.wallet.address,
      "X-SpaceRouter-Identity-Address": this.wallet.address,
      "X-SpaceRouter-Challenge-Signature": signature,
      "X-SpaceRouter-Challenge": challenge,
    };
  }

  /**
   * Validate a receipt from the gateway.
   */
  validateReceipt(receipt: ReceiptData): ValidationResult {
    return this.validator.validate(receipt);
  }

  /**
   * Sign a validated receipt (EIP-712).
   *
   * @param receipt - Receipt data from the gateway (with requestId as hex bytes16).
   * @returns Hex-encoded signature.
   */
  async signReceipt(receipt: Receipt): Promise<Hex> {
    return await this.wallet.signReceipt(receipt);
  }

  /**
   * Make a SPACE-paid fetch request through the proxy.
   *
   * Handles challenge → auth → request flow automatically.
   * Note: This uses standard fetch without proxy support.
   * For actual proxied requests, use the auth headers with an HTTP client
   * that supports proxy configuration.
   */
  async fetch(
    url: string,
    options: RequestInit = {},
  ): Promise<{ challenge: string; headers: AuthHeaders }> {
    const challenge = await this.requestChallenge();
    const authHeaders = await this.buildAuthHeaders(challenge);
    return { challenge, headers: authHeaders };
  }

  /**
   * Parse a length-prefixed receipt frame from raw bytes.
   */
  static readReceiptFrame(data: Uint8Array): ReceiptData | null {
    if (data.length < 4) return null;
    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const length = view.getUint32(0, false); // big-endian
    if (data.length < 4 + length) return null;
    try {
      const payload = new TextDecoder().decode(data.slice(4, 4 + length));
      return JSON.parse(payload);
    } catch {
      return null;
    }
  }

  /**
   * Encode a signature response as a length-prefixed frame.
   */
  static encodeSignatureFrame(signature: string): Uint8Array {
    const payload = new TextEncoder().encode(JSON.stringify({ signature }));
    const frame = new Uint8Array(4 + payload.length);
    const view = new DataView(frame.buffer);
    view.setUint32(0, payload.length, false); // big-endian
    frame.set(payload, 4);
    return frame;
  }
}
