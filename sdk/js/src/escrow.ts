/**
 * Escrow contract types and constants for SpaceRouter payments.
 *
 * Shared between v0.2.2 node payments and v0.2.3 client payments.
 * @module escrow
 */

import type { Address, Hex } from "viem";

/**
 * EIP-712 domain for the SpaceRouter Escrow contract.
 */
export const RECEIPT_EIP712_DOMAIN = {
  name: "SpaceRouterEscrow" as const,
  version: "1" as const,
} as const;

/**
 * EIP-712 types for payment receipts.
 */
export const receiptTypes = {
  Receipt: [
    { name: "clientPaymentAddress", type: "address" },
    { name: "nodeCollectionAddress", type: "address" },
    { name: "requestId", type: "bytes16" },
    { name: "dataBytes", type: "uint256" },
    { name: "priceWei", type: "uint256" },
    { name: "timestamp", type: "uint256" },
  ],
} as const;

/**
 * A payment receipt for EIP-712 signing.
 */
export interface Receipt {
  clientPaymentAddress: Address;
  nodeCollectionAddress: Address;
  requestId: Hex;
  dataBytes: bigint;
  priceWei: bigint;
  timestamp: bigint;
}

/**
 * Escrow contract ABI (subset for settleBatch).
 */
export const ESCROW_ABI = [
  {
    type: "function",
    name: "settleBatch",
    inputs: [
      {
        name: "signedReceipts",
        type: "tuple[]",
        components: [
          {
            name: "receipt",
            type: "tuple",
            components: [
              { name: "clientPaymentAddress", type: "address" },
              { name: "nodeCollectionAddress", type: "address" },
              { name: "requestId", type: "bytes16" },
              { name: "dataBytes", type: "uint256" },
              { name: "priceWei", type: "uint256" },
              { name: "timestamp", type: "uint256" },
            ],
          },
          { name: "signature", type: "bytes" },
        ],
      },
    ],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "deposit",
    inputs: [],
    outputs: [],
    stateMutability: "payable",
  },
  {
    type: "function",
    name: "withdraw",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
    stateMutability: "nonpayable",
  },
  {
    type: "function",
    name: "balanceOf",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
  },
] as const;

/**
 * EscrowClient for interacting with the SpaceRouter Escrow contract.
 */
export class EscrowClient {
  readonly contractAddress: Address;
  readonly chainId: number;

  constructor(options: { contractAddress: Address; chainId?: number }) {
    this.contractAddress = options.contractAddress;
    this.chainId = options.chainId ?? 102031;
  }
}
