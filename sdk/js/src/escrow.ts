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
      functionName: "getBalance",
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

  /**
   * Pending withdrawal request for `address`.
   *
   * Returns `{amount, readyAt}` for backward compatibility with earlier
   * stub implementations. The on-chain function is `getWithdrawalRequest`
   * and returns `(amount, unlockAt, exists)`; we surface `unlockAt` as
   * `readyAt` and drop `exists` (callers can derive it from
   * `amount > 0n`).
   *
   * Use this to see the locked-but-pending amount during a withdrawal.
   * Important: `balance(address)` does **NOT** include this amount —
   * the on-chain balance is only debited when `executeWithdrawal`
   * completes. See `initiateWithdrawal` for the three-phase lifecycle.
   */
  async withdrawalRequest(
    address: `0x${string}`,
  ): Promise<WithdrawalRequest> {
    const [amount, unlockAt /* exists */] = await this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "getWithdrawalRequest",
      args: [getAddress(address)],
    });
    return { amount, readyAt: unlockAt };
  }

  /**
   * Whether the request UUID has already been consumed for `client`.
   *
   * The deployed contract takes the UUID **string** directly (and hashes
   * internally). Earlier versions of this SDK accepted a 32-byte hash;
   * for backward compat we accept either: a 66-char `0x...` hash is
   * rejected since the on-chain method no longer takes hashes; pass
   * the UUID string instead.
   */
  async isNonceUsed(
    client: `0x${string}`,
    requestUUID: string,
  ): Promise<boolean> {
    return this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "isNonceUsed",
      args: [getAddress(client), requestUUID],
    });
  }

  /** On-chain withdrawal delay (seconds). 5 days on testnet. */
  async withdrawalDelay(): Promise<bigint> {
    return this._publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "WITHDRAWAL_DELAY",
    });
  }

  // ── Writes ──────────────────────────────────────────────────────────

  private _requireSigner(): { wallet: WalletClient; account: Account } {
    if (!this._walletClient || !this._account) {
      throw new Error("EscrowClient: signer required for write operations");
    }
    return { wallet: this._walletClient, account: this._account };
  }

  /**
   * Send a write tx and wait for it to be mined before resolving. All write
   * helpers below funnel through this so callers can immediately query state
   * (e.g. `balance`) right after `await deposit(...)` and see post-tx values.
   */
  private async _sendAndWait(args: Parameters<WalletClient["writeContract"]>[0]): Promise<Hash> {
    const { wallet } = this._requireSigner();
    const hash = await wallet.writeContract(args);
    await this._publicClient.waitForTransactionReceipt({ hash });
    return hash;
  }

  /** Approve the escrow contract to pull `amount` tokens. Awaits receipt. */
  async approve(amount: bigint): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { account } = this._requireSigner();
    return this._sendAndWait({
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
   * (which itself waits for receipt). Returns once the deposit tx is mined.
   */
  async deposit(amount: bigint, autoApprove = true): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { account } = this._requireSigner();

    if (autoApprove) {
      const current = await this._publicClient.readContract({
        address: this.tokenAddress,
        abi: ERC20_ABI,
        functionName: "allowance",
        args: [account.address, this.contractAddress],
      });
      if (current < amount) {
        await this.approve(amount);  // already awaits receipt
      }
    }

    return this._sendAndWait({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "deposit",
      args: [amount],
    });
  }

  /**
   * Phase 1 of 3 — record a withdrawal request with a 5-day timelock.
   * Awaits receipt.
   *
   * This call does **not** move tokens. It only stores
   * `(amount, unlockAt)` on-chain so the funds are reserved for the
   * eventual `executeWithdrawal` and the timelock can run. Therefore
   * `balance(address)` is unchanged after `initiateWithdrawal`
   * resolves. Query `withdrawalRequest(address)` to see the
   * locked-but-pending amount.
   *
   * Lifecycle:
   *   1. `initiateWithdrawal(amount)` — record request, no balance
   *      change.
   *   2. `executeWithdrawal()` — after timelock elapses, actually
   *      transfers tokens out and debits `balance`.
   *   3. `cancelWithdrawal()` — at any point before step 2, clear
   *      the request. Also no balance change because no debit ever
   *      happened.
   */
  async initiateWithdrawal(amount: bigint): Promise<Hash> {
    if (amount <= 0n) throw new Error("amount must be positive");
    const { account } = this._requireSigner();
    return this._sendAndWait({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "initiateWithdrawal",
      args: [amount],
    });
  }

  /**
   * Phase 2 of 3 — finalise a withdrawal whose timelock has elapsed.
   * Awaits receipt.
   *
   * This is the **only** phase that actually moves tokens. The
   * contract transfers the previously-requested amount to the client
   * and debits `balance(address)` by the same amount. Reverts if no
   * request exists or the unlock time has not yet passed. See
   * `initiateWithdrawal` for the full lifecycle.
   */
  async executeWithdrawal(): Promise<Hash> {
    const { account } = this._requireSigner();
    return this._sendAndWait({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "executeWithdrawal",
    });
  }

  /**
   * Phase 3 (alternate) of 3 — clear the pending withdrawal request.
   * Awaits receipt.
   *
   * Removes the on-chain request record. Because `initiateWithdrawal`
   * never debited the balance, this call also produces **no balance
   * change** — that is by design, not a bug. `balance(address)` was
   * already correct throughout. See `initiateWithdrawal` for the
   * three-phase lifecycle.
   */
  async cancelWithdrawal(): Promise<Hash> {
    const { account } = this._requireSigner();
    return this._sendAndWait({
      account,
      chain: null,
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "cancelWithdrawal",
    });
  }
}
