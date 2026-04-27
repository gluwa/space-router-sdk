/**
 * Consumer-side wallet for SPACE payment auth + receipt signing.
 *
 * Mirrors `ClientPaymentWallet` from the Python SDK:
 *   - EIP-191 challenge signing (used for proxy CONNECT auth).
 *   - EIP-712 receipt signing (used to acknowledge a metered request).
 *
 * Per protocol §4, the wire format for the consumer's address in the
 * `X-SpaceRouter-*` headers is **lowercase** 0x-hex. The internal viem
 * account address is checksummed; we lowercase only when emitting.
 */

import { privateKeyToAccount, type PrivateKeyAccount } from "viem/accounts";
import {
  recoverReceiptSigner,
  type EIP712Domain,
  type Receipt,
} from "./eip712.js";

/** The four lowercase-keyed proxy headers required for v1.5 auth. */
export type AuthHeaders = {
  "X-SpaceRouter-Payment-Address": string;
  "X-SpaceRouter-Identity-Address": string;
  "X-SpaceRouter-Challenge": string;
  "X-SpaceRouter-Challenge-Signature": string;
};

const RECEIPT_TYPES = {
  Receipt: [
    { name: "clientAddress", type: "address" },
    { name: "nodeAddress", type: "bytes32" },
    { name: "requestUUID", type: "string" },
    { name: "dataAmount", type: "uint256" },
    { name: "totalPrice", type: "uint256" },
  ],
} as const;

export class ClientPaymentWallet {
  private readonly _account: PrivateKeyAccount;
  /** Lowercase 0x-hex form of the wallet address (wire format). */
  public readonly address: `0x${string}`;
  /** Checksummed form (viem-native). Useful for typed-data invocations. */
  public readonly checksumAddress: `0x${string}`;

  constructor(privateKey: `0x${string}`) {
    if (!privateKey) {
      throw new Error("Private key is required");
    }
    this._account = privateKeyToAccount(privateKey);
    this.checksumAddress = this._account.address;
    this.address = this._account.address.toLowerCase() as `0x${string}`;
  }

  /**
   * Sign a Leg-1 challenge with EIP-191 (`personal_sign`).
   *
   * The signed payload is `space-router:challenge:<challenge>`, mirroring
   * the Python SDK. Returns a 65-byte 0x-prefixed hex string.
   */
  async signChallenge(challenge: string): Promise<`0x${string}`> {
    const message = `space-router:challenge:${challenge}`;
    return this._account.signMessage({ message });
  }

  /** EIP-712 receipt signing — uses the bound viem account directly. */
  async signReceipt(
    receipt: Receipt,
    domain: EIP712Domain,
  ): Promise<`0x${string}`> {
    return this._account.signTypedData({
      domain: {
        name: domain.name,
        version: domain.version,
        chainId: domain.chainId,
        verifyingContract: domain.verifyingContract,
      },
      types: RECEIPT_TYPES,
      primaryType: "Receipt",
      message: {
        clientAddress: receipt.clientAddress,
        nodeAddress: receipt.nodeAddress,
        requestUUID: receipt.requestUUID,
        dataAmount: receipt.dataAmount,
        totalPrice: receipt.totalPrice,
      },
    });
  }

  /**
   * Build the four `X-SpaceRouter-*` proxy CONNECT headers.
   *
   * - `X-SpaceRouter-Payment-Address` and `X-SpaceRouter-Identity-Address`
   *   are the same wallet for v1.5 (per protocol §4).
   * - The address is **lowercased** before emission (the gateway lowercases
   *   before recovery; checksum casing would mismatch).
   *
   * Returns a Promise because signing is asynchronous under viem; the
   * caller awaits and then forwards the resulting record verbatim into
   * the `headers` map of the proxy CONNECT request.
   */
  async buildAuthHeaders(challenge: string): Promise<AuthHeaders> {
    const signature = await this.signChallenge(challenge);
    return {
      "X-SpaceRouter-Payment-Address": this.address,
      "X-SpaceRouter-Identity-Address": this.address,
      "X-SpaceRouter-Challenge": challenge,
      "X-SpaceRouter-Challenge-Signature": signature,
    };
  }

  /**
   * Verify a receipt signature recovers to `expected`.
   *
   * Compares lowercased forms — EIP-712 returns checksummed addresses,
   * but downstream code typically holds lowercase wire format.
   */
  static async verifyReceiptSignature(
    receipt: Receipt,
    signature: `0x${string}`,
    domain: EIP712Domain,
    expected: `0x${string}`,
  ): Promise<boolean> {
    try {
      const recovered = await recoverReceiptSigner(receipt, signature, domain);
      return recovered.toLowerCase() === expected.toLowerCase();
    } catch {
      return false;
    }
  }
}
