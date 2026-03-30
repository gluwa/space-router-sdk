/**
 * Client payment wallet for v0.2.3 SPACE payments.
 *
 * Handles EIP-191 challenge signing and EIP-712 receipt signing for
 * client-to-gateway payment flows using viem.
 * @module payment/clientWallet
 */

import {
  type Address,
  type Hex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";

import { RECEIPT_EIP712_DOMAIN, receiptTypes, type Receipt } from "../escrow.js";

export interface ClientWalletOptions {
  /** Client private key for signing */
  privateKey: Hex;
  /** Chain ID for EIP-712 domain (default: Creditcoin 102031) */
  chainId?: number;
  /** Escrow contract address for EIP-712 domain */
  escrowContract?: Address;
}

/**
 * Wallet for client SPACE payment operations.
 *
 * Provides EIP-191 signing for authentication challenges and
 * EIP-712 signing for payment receipts.
 */
export class ClientWallet {
  private account: ReturnType<typeof privateKeyToAccount>;
  private chainId: number;
  private escrowContract: Address;

  constructor(options: ClientWalletOptions) {
    this.account = privateKeyToAccount(options.privateKey);
    this.chainId = options.chainId ?? 102031;
    this.escrowContract = options.escrowContract ?? ("0x" + "0".repeat(40)) as Address;
  }

  /** Client payment/identity address (lowercase). */
  get address(): string {
    return this.account.address.toLowerCase();
  }

  /** Client payment/identity address (checksummed). */
  get checksumAddress(): Address {
    return this.account.address;
  }

  /**
   * Sign an authentication challenge (EIP-191).
   *
   * Message format: `space-router:challenge:{challenge}`
   *
   * @returns signature hex string
   */
  async signChallenge(challenge: string): Promise<Hex> {
    const message = `space-router:challenge:${challenge}`;
    return await this.account.signMessage({ message });
  }

  /**
   * Sign a payment receipt (EIP-712).
   *
   * @param receipt - Receipt data from the gateway
   * @returns signature hex string
   */
  async signReceipt(receipt: Receipt): Promise<Hex> {
    if (this.escrowContract === ("0x" + "0".repeat(40)) as Address) {
      throw new Error("Escrow contract address required for receipt signing");
    }

    return await this.account.signTypedData({
      domain: {
        ...RECEIPT_EIP712_DOMAIN,
        chainId: this.chainId,
        verifyingContract: this.escrowContract,
      },
      types: receiptTypes,
      primaryType: "Receipt",
      message: receipt,
    });
  }
}
