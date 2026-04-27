/**
 * EIP-712 typed-data signing for `TokenPaymentEscrow` receipts.
 *
 * Mirrors the Python SDK at `sdk/python/src/spacerouter/payment/eip712.py`.
 * MUST produce byte-identical signatures for the canonical test vector at
 * `internal-docs/v1.5-consumer-protocol.md` §7.
 *
 * Implementation notes:
 *   - All `uint256` fields are `bigint` end-to-end (per protocol §2).
 *   - Addresses on the wire are lowercase, but viem requires checksummed
 *     addresses inside typed data; we normalise via `getAddress()`.
 *   - Signature is canonical 65-byte `r || s || v` with v ∈ {27, 28}, which
 *     is what viem's `signTypedData` emits.
 */

import {
  getAddress,
  recoverTypedDataAddress,
  type Hex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";

/** EIP-712 domain separator parameters for `TokenPaymentEscrow`. */
export interface EIP712Domain {
  name: string;
  version: string;
  chainId: bigint;
  verifyingContract: `0x${string}`;
}

/**
 * On-chain `Receipt` struct.
 *
 * Layout matches `Receipt(address clientAddress,bytes32 nodeAddress,
 * string requestUUID,uint256 dataAmount,uint256 totalPrice)` exactly.
 */
export interface Receipt {
  clientAddress: `0x${string}`;
  /** 32-byte 0x-hex string. Use `addressToBytes32(stakingAddress)`. */
  nodeAddress: `0x${string}`;
  requestUUID: string;
  dataAmount: bigint;
  totalPrice: bigint;
}

/** Viem-compatible types object for the Receipt typed-data envelope. */
const RECEIPT_TYPES = {
  Receipt: [
    { name: "clientAddress", type: "address" },
    { name: "nodeAddress", type: "bytes32" },
    { name: "requestUUID", type: "string" },
    { name: "dataAmount", type: "uint256" },
    { name: "totalPrice", type: "uint256" },
  ],
} as const;

function normaliseDomain(domain: EIP712Domain) {
  return {
    name: domain.name,
    version: domain.version,
    chainId: domain.chainId,
    verifyingContract: getAddress(domain.verifyingContract),
  };
}

function normaliseMessage(receipt: Receipt) {
  return {
    clientAddress: getAddress(receipt.clientAddress),
    nodeAddress: receipt.nodeAddress,
    requestUUID: receipt.requestUUID,
    dataAmount: receipt.dataAmount,
    totalPrice: receipt.totalPrice,
  };
}

/**
 * Zero-left-pad a 20-byte EVM address to a 32-byte hex string.
 *
 * Mirrors the Python `address_to_bytes32` helper, which lowercases its input
 * before padding. The result is suitable for the `nodeAddress` field of a
 * `Receipt`.
 *
 * Example: `0xAbC...123` → `0x000000000000000000000000abc...123`.
 */
export function addressToBytes32(address: `0x${string}`): `0x${string}` {
  if (!/^0x[0-9a-fA-F]{40}$/.test(address)) {
    throw new Error(`addressToBytes32: invalid 20-byte address: ${address}`);
  }
  const stripped = address.slice(2).toLowerCase();
  return `0x${"0".repeat(24)}${stripped}` as `0x${string}`;
}

/**
 * Sign a `Receipt` using EIP-712 typed data.
 *
 * Returns a 65-byte 0x-prefixed hex string (`r || s || v`, v ∈ {27,28}).
 */
export async function signReceipt(
  privateKey: `0x${string}`,
  receipt: Receipt,
  domain: EIP712Domain,
): Promise<`0x${string}`> {
  const account = privateKeyToAccount(privateKey);
  const signature = await account.signTypedData({
    domain: normaliseDomain(domain),
    types: RECEIPT_TYPES,
    primaryType: "Receipt",
    message: normaliseMessage(receipt),
  });
  return signature as Hex;
}

/**
 * Recover the signer address from a `Receipt` + signature pair.
 *
 * Returns the recovered address in viem's checksummed form. Callers that
 * require lowercase comparison should `.toLowerCase()` both sides.
 */
export async function recoverReceiptSigner(
  receipt: Receipt,
  signature: `0x${string}`,
  domain: EIP712Domain,
): Promise<`0x${string}`> {
  return recoverTypedDataAddress({
    domain: normaliseDomain(domain),
    types: RECEIPT_TYPES,
    primaryType: "Receipt",
    message: normaliseMessage(receipt),
    signature,
  });
}
