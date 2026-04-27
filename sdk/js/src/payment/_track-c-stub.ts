/**
 * TRACK-C STUB — temporary local mirror of Track C's `payment/` module.
 *
 * Track D was developed in parallel on a separate branch
 * (`feat/v1.5-track-d`) while Track C owns the real signing primitives on
 * `feat/v1.5-track-c`.  After both branches merge to `main`, the integration
 * PR replaces every `_track-c-stub` import with the real module.  Find every
 * call site by searching for `TODO(track-c)`.
 *
 * Reference: `internal-docs/v1.5-consumer-protocol.md` §2 (EIP-712 domain),
 * §4 (EIP-191 auth message), §7 (canonical test vector).
 */

import {
  privateKeyToAccount,
  type PrivateKeyAccount,
} from "viem/accounts";
import { getAddress, type Hex } from "viem";

// ---------------------------------------------------------------------------
// Types — must match Track C's eip712.ts / clientWallet.ts public surface.
// ---------------------------------------------------------------------------

export interface EIP712Domain {
  name: string;
  version: string;
  chainId: number;
  verifyingContract: `0x${string}`;
}

export interface Receipt {
  clientAddress: `0x${string}`;
  /** bytes32, zero-left-padded staking address. */
  nodeAddress: `0x${string}`;
  requestUUID: string;
  dataAmount: bigint;
  totalPrice: bigint;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Convert a 20-byte address to `bytes32` by lowercasing then zero-left-padding
 * to 32 bytes.  Per protocol §2: this is `bytes32(stakingAddress)`.
 */
export function addressToBytes32(addr: string): `0x${string}` {
  const lower = addr.toLowerCase();
  if (!lower.startsWith("0x")) {
    throw new Error(`addressToBytes32: address must be 0x-prefixed, got ${addr}`);
  }
  const hex = lower.slice(2);
  if (hex.length !== 40) {
    throw new Error(
      `addressToBytes32: expected 20-byte (40 hex char) address, got ${hex.length} chars`,
    );
  }
  // 24 zero nibbles + 40 hex address = 64 hex chars (32 bytes).
  return `0x${"0".repeat(24)}${hex}` as `0x${string}`;
}

const RECEIPT_TYPES = {
  Receipt: [
    { name: "clientAddress", type: "address" },
    { name: "nodeAddress", type: "bytes32" },
    { name: "requestUUID", type: "string" },
    { name: "dataAmount", type: "uint256" },
    { name: "totalPrice", type: "uint256" },
  ],
} as const;

/**
 * Sign a Receipt struct under the given EIP-712 domain.
 *
 * Returns a 65-byte hex signature with `v ∈ {27, 28}` per protocol §7.
 */
export async function signReceipt(
  privateKey: Hex,
  receipt: Receipt,
  domain: EIP712Domain,
): Promise<`0x${string}`> {
  const account = privateKeyToAccount(privateKey);
  const sig = await account.signTypedData({
    domain: {
      name: domain.name,
      version: domain.version,
      chainId: domain.chainId,
      verifyingContract: domain.verifyingContract,
    },
    types: RECEIPT_TYPES,
    primaryType: "Receipt",
    message: {
      clientAddress: getAddress(receipt.clientAddress),
      nodeAddress: receipt.nodeAddress,
      requestUUID: receipt.requestUUID,
      dataAmount: receipt.dataAmount,
      totalPrice: receipt.totalPrice,
    },
  });
  return sig;
}

// ---------------------------------------------------------------------------
// ClientPaymentWallet
// ---------------------------------------------------------------------------

export interface PaymentAuthHeaders {
  "X-SpaceRouter-Payment-Address": string;
  "X-SpaceRouter-Identity-Address": string;
  "X-SpaceRouter-Challenge": string;
  "X-SpaceRouter-Challenge-Signature": string;
}

/**
 * Stub mirror of Track C's `ClientPaymentWallet`.  Only the surface that
 * Track D consumes is implemented; replace with the real export at integration
 * time.
 */
export class ClientPaymentWallet {
  private readonly _account: PrivateKeyAccount;
  private readonly _privateKey: Hex;

  constructor(privateKey: Hex) {
    this._privateKey = privateKey;
    this._account = privateKeyToAccount(privateKey);
  }

  /** Lowercased 0x-prefixed address. */
  get address(): `0x${string}` {
    return this._account.address.toLowerCase() as `0x${string}`;
  }

  /** EIP-191 personal_sign over a UTF-8 string. */
  async signMessage(message: string): Promise<`0x${string}`> {
    return this._account.signMessage({ message });
  }

  /** EIP-712 sign of a Receipt under the v1.5 domain. */
  async signReceipt(
    receipt: Receipt,
    domain: EIP712Domain,
  ): Promise<`0x${string}`> {
    return signReceipt(this._privateKey, receipt, domain);
  }

  /** Build the four `X-SpaceRouter-*` per-request payment headers. */
  async buildAuthHeaders(challenge: string): Promise<PaymentAuthHeaders> {
    const sig = await this.signMessage(challenge);
    const addr = this.address;
    return {
      "X-SpaceRouter-Payment-Address": addr,
      // v1.5: identity wallet === payment wallet.
      "X-SpaceRouter-Identity-Address": addr,
      "X-SpaceRouter-Challenge": challenge,
      "X-SpaceRouter-Challenge-Signature": sig,
    };
  }
}
