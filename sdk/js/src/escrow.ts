/**
 * Consumer-facing client for the on-chain `TokenPaymentEscrow` contract.
 *
 * Mirrors the Python SDK's `EscrowClient` (`sdk/python/src/spacerouter/escrow.py`).
 * Reads use a viem `PublicClient` and writes use a `WalletClient` that wraps
 * either a private key or an externally-provided viem `Account`.
 *
 * Amount semantics: every monetary value is `bigint` end-to-end. Pass
 * decimals (10n ** 18n) for SPACE tokens. Never `number`.
 */

import {
  createPublicClient,
  createWalletClient,
  getAddress,
  http,
  keccak256,
  toBytes,
  type Account,
  type Hash,
  type PublicClient,
  type WalletClient,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { ERC20_ABI, ESCROW_ABI } from "./escrow.abi.js";

export interface EscrowClientOptions {
  rpcUrl: string;
  contractAddress: `0x${string}`;
  tokenAddress: `0x${string}`;
  /** Hex private key. Mutually exclusive with `account`. */
  privateKey?: `0x${string}`;
  /** Pre-built viem account. Mutually exclusive with `privateKey`. */
  account?: Account;
}

export interface WithdrawalRequest {
  amount: bigint;
  readyAt: bigint;
}

export class EscrowClient {
  public readonly contractAddress: `0x${string}`;
  public readonly tokenAddress: `0x${string}`;

  private readonly _publicClient: PublicClient;
  private readonly _walletClient: WalletClient | null;
  private readonly _account: Account | null;

  constructor(options: EscrowClientOptions) {
    if (options.privateKey && options.account) {
      throw new Error("Pass either privateKey or account, not both");
    }
    this.contractAddress = getAddress(options.contractAddress);
    this.tokenAddress = getAddress(options.tokenAddress);

    this._publicClient = createPublicClient({
      transport: http(options.rpcUrl),
    });

    if (options.privateKey) {
      this._account = privateKeyToAccount(options.privateKey);
    } else if (options.account) {
      this._account = options.account;
    } else {
      this._account = null;
    }

    this._walletClient = this._account
      ? createWalletClient({
          account: this._account,
          transport: http(options.rpcUrl),
        })
      : null;
  }

  /** Address of the bound signer (checksummed), or `null` if read-only. */
  get address(): `0x${string}` | null {
    return this._account?.address ?? null;
  }

  /** Underlying viem `PublicClient`. Exposed for tests/integration. */
  get publicClient(): PublicClient {
    return this._publicClient;
  }

  // ── Reads ───────────────────────────────────────────────────────────

  /** Escrowed deposit balance (in token wei) for `address`. */
  async balance(address: `0x${string}`): Promise<bigint> {
    return this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "balanceOf",
      args: [getAddress(address)],
    });
  }

  /** ERC-20 wallet balance (un-deposited tokens) for `address`. */
  async tokenBalance(address: `0x${string}`): Promise<bigint> {
    return this._publicClient.readContract({
      address: this.tokenAddress,
      abi: ERC20_ABI,
      functionName: "balanceOf",
      args: [getAddress(address)],
    });
  }

  /** Pending withdrawal request for `address` (`amount`, `readyAt`). */
  async withdrawalRequest(
    address: `0x${string}`,
  ): Promise<WithdrawalRequest> {
    const result = await this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "withdrawalRequestOf",
      args: [getAddress(address)],
    });
    const [amount, readyAt] = result;
    return { amount, readyAt };
  }

  /**
   * Whether `uuidHash` has already been consumed for `client`.
   *
   * `uuidHash` MUST be the keccak-256 of the request UUID string. Pass a raw
   * 32-byte hex if you have already hashed it; pass a UTF-8 string and we'll
   * hash it for you.
   */
  async isNonceUsed(
    client: `0x${string}`,
    uuidHash: `0x${string}` | string,
  ): Promise<boolean> {
    const hash = (uuidHash.startsWith("0x") && uuidHash.length === 66
      ? uuidHash
      : keccak256(toBytes(uuidHash))) as `0x${string}`;
    return this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "usedNonces",
      args: [getAddress(client), hash],
    });
  }

  /** On-chain withdrawal delay (seconds). 5 days on testnet. */
  async withdrawalDelay(): Promise<bigint> {
    return this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "withdrawalDelay",
    });
  }

  // ── Writes ──────────────────────────────────────────────────────────

  private _requireSigner(): { wallet: WalletClient; account: Account } {
    if (!this._walletClient || !this._account) {
      throw new Error("EscrowClient: signer required for write operations");
    }
    return { wallet: this._walletClient, account: this._account };
  }

  /** Approve the escrow contract to pull `amount` tokens. */
  async approve(amount: bigint): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { wallet, account } = this._requireSigner();
    return wallet.writeContract({
      account,
      chain: null,
      address: this.tokenAddress,
      abi: ERC20_ABI,
      functionName: "approve",
      args: [this.contractAddress, amount],
    });
  }

  /**
   * Deposit `amount` tokens into escrow. If `autoApprove` is true (default)
   * and the current allowance is insufficient, sends an `approve` tx first
   * and waits for it to land.
   */
  async deposit(amount: bigint, autoApprove = true): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { wallet, account } = this._requireSigner();

    if (autoApprove) {
      const current = await this._publicClient.readContract({
        address: this.tokenAddress,
        abi: ERC20_ABI,
        functionName: "allowance",
        args: [account.address, this.contractAddress],
      });
      if (current < amount) {
        const approvalHash = await this.approve(amount);
        await this._publicClient.waitForTransactionReceipt({
          hash: approvalHash,
        });
      }
    }

    return wallet.writeContract({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "deposit",
      args: [amount],
    });
  }

  /** Begin a withdrawal of `amount` tokens (timelock applies). */
  async initiateWithdrawal(amount: bigint): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { wallet, account } = this._requireSigner();
    return wallet.writeContract({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "initiateWithdrawal",
      args: [amount],
    });
  }

  /** Finalise a withdrawal whose timelock has elapsed. */
  async executeWithdrawal(): Promise<Hash> {
    const { wallet, account } = this._requireSigner();
    return wallet.writeContract({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "executeWithdrawal",
    });
  }

  /** Cancel a pending withdrawal. */
  async cancelWithdrawal(): Promise<Hash> {
    const { wallet, account } = this._requireSigner();
    return wallet.writeContract({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "cancelWithdrawal",
    });
  }
}
