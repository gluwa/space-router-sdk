/**
 * SpaceRouter EscrowClient — interact with the SpaceRouterEscrow contract.
 *
 * Uses viem for contract interactions and EIP-712 signing.
 * @module escrow
 */
import {
  type Address,
  type Hex,
  type PublicClient,
  type WalletClient,
  createPublicClient,
  createWalletClient,
  http,
  parseAbi,
  getContract,
  type GetContractReturnType,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";

// ── ABI (minimal) ────────────────────────────────────────────────

export const ESCROW_ABI = parseAbi([
  "function deposit(uint256 amount) external",
  "function escrowBalance(address payer) external view returns (uint256)",
  "function initiateWithdrawal(uint256 amount) external",
  "function completeWithdrawal() external",
  "function cancelWithdrawal() external",
  "function pendingWithdrawal(address payer) external view returns (uint256 amount, uint256 unlockTime)",
  "function settleBatch((( address clientPaymentAddress, address nodeCollectionAddress, bytes16 requestId, uint256 dataBytes, uint256 priceWei, uint256 timestamp) receipt, bytes signature)[] receipts) external returns (uint256 paid, uint256 skipped, uint256 underfunded)",
  "function claimedRequests(bytes16) external view returns (bool)",
  "function spaceToken() external view returns (address)",
  "function WITHDRAWAL_DELAY() external view returns (uint256)",
  "event Deposited(address indexed payer, uint256 amount)",
  "event ReceiptSettled(bytes16 indexed requestId, address indexed payer, address indexed payee, uint256 receiptAmount, uint256 paidAmount)",
  "event WithdrawalInitiated(address indexed payer, uint256 amount, uint256 unlockTime)",
  "event WithdrawalCompleted(address indexed payer, uint256 amount)",
  "event WithdrawalCancelled(address indexed payer)",
]);

export const ERC20_ABI = parseAbi([
  "function approve(address spender, uint256 amount) external returns (bool)",
  "function allowance(address owner, address spender) external view returns (uint256)",
  "function balanceOf(address account) external view returns (uint256)",
]);

// ── EIP-712 Receipt Type ─────────────────────────────────────────

export const RECEIPT_EIP712_DOMAIN = {
  name: "SpaceRouterEscrow" as const,
  version: "1" as const,
};

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

// ── Types ────────────────────────────────────────────────────────

export interface Receipt {
  clientPaymentAddress: Address;
  nodeCollectionAddress: Address;
  requestId: Hex;
  dataBytes: bigint;
  priceWei: bigint;
  timestamp: bigint;
}

export interface SignedReceipt {
  receipt: Receipt;
  signature: Hex;
}

export interface PendingWithdrawal {
  amount: bigint;
  unlockTime: bigint;
}

export interface SettlementResult {
  paid: bigint;
  skipped: bigint;
  underfunded: bigint;
  txHash: Hex;
}

export interface EscrowClientOptions {
  /** Creditcoin RPC URL */
  rpcUrl: string;
  /** SpaceRouterEscrow contract address */
  contractAddress: Address;
  /** Chain ID */
  chainId: number;
  /** Private key for write operations (optional for read-only) */
  privateKey?: Hex;
}

// ── EscrowClient ─────────────────────────────────────────────────

export class EscrowClient {
  private publicClient: PublicClient;
  private walletClient: WalletClient | null;
  private contractAddress: Address;
  private chainId: number;
  private account: Address | null;

  constructor(options: EscrowClientOptions) {
    this.contractAddress = options.contractAddress;
    this.chainId = options.chainId;

    this.publicClient = createPublicClient({
      transport: http(options.rpcUrl),
    });

    if (options.privateKey) {
      const account = privateKeyToAccount(options.privateKey);
      this.account = account.address;
      this.walletClient = createWalletClient({
        account,
        transport: http(options.rpcUrl),
      });
    } else {
      this.account = null;
      this.walletClient = null;
    }
  }

  /** Gateway wallet address */
  get address(): Address | null {
    return this.account;
  }

  // ── Read Operations ──────────────────────────────────────────

  /** Query escrow balance for an address (in wei). */
  async balance(address: Address): Promise<bigint> {
    return await this.publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "escrowBalance",
      args: [address],
    });
  }

  /** Query pending withdrawal for an address. */
  async pendingWithdrawal(address: Address): Promise<PendingWithdrawal> {
    const [amount, unlockTime] = await this.publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "pendingWithdrawal",
      args: [address],
    });
    return { amount, unlockTime };
  }

  /** Check if a request ID has been claimed. */
  async isClaimed(requestId: Hex): Promise<boolean> {
    return await this.publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "claimedRequests",
      args: [requestId],
    });
  }

  /** Get the SPACE token contract address. */
  async tokenAddress(): Promise<Address> {
    return await this.publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "spaceToken",
    });
  }

  /** Query SPACE token balance (not escrowed). */
  async tokenBalance(address: Address): Promise<bigint> {
    const token = await this.tokenAddress();
    return await this.publicClient.readContract({
      address: token,
      abi: ERC20_ABI,
      functionName: "balanceOf",
      args: [address],
    });
  }

  /** Get the withdrawal delay in seconds. */
  async withdrawalDelay(): Promise<bigint> {
    return await this.publicClient.readContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "WITHDRAWAL_DELAY",
    });
  }

  // ── Write Operations ─────────────────────────────────────────

  private requireSigner(): WalletClient {
    if (!this.walletClient || !this.account) {
      throw new Error("Private key required for write operations");
    }
    return this.walletClient;
  }

  /** Deposit SPACE tokens into escrow. Returns tx hash. */
  async deposit(amount: bigint): Promise<Hex> {
    const wallet = this.requireSigner();
    if (amount <= 0n) throw new Error("Amount must be positive");

    // Check and approve if needed
    const token = await this.tokenAddress();
    const allowance = await this.publicClient.readContract({
      address: token,
      abi: ERC20_ABI,
      functionName: "allowance",
      args: [this.account!, this.contractAddress],
    });

    if (allowance < amount) {
      const approveTx = await wallet.writeContract({
        address: token,
        abi: ERC20_ABI,
        functionName: "approve",
        args: [this.contractAddress, amount],
        chain: null,
      });
      await this.publicClient.waitForTransactionReceipt({ hash: approveTx });
    }

    const tx = await wallet.writeContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "deposit",
      args: [amount],
      chain: null,
    });
    await this.publicClient.waitForTransactionReceipt({ hash: tx });
    return tx;
  }

  /** Initiate escrow withdrawal. Returns tx hash. */
  async initiateWithdrawal(amount: bigint): Promise<Hex> {
    const wallet = this.requireSigner();
    if (amount <= 0n) throw new Error("Amount must be positive");

    const tx = await wallet.writeContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "initiateWithdrawal",
      args: [amount],
      chain: null,
    });
    await this.publicClient.waitForTransactionReceipt({ hash: tx });
    return tx;
  }

  /** Complete pending withdrawal after timelock. Returns tx hash. */
  async completeWithdrawal(): Promise<Hex> {
    const wallet = this.requireSigner();
    const tx = await wallet.writeContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "completeWithdrawal",
      chain: null,
    });
    await this.publicClient.waitForTransactionReceipt({ hash: tx });
    return tx;
  }

  /** Cancel pending withdrawal. Returns tx hash. */
  async cancelWithdrawal(): Promise<Hex> {
    const wallet = this.requireSigner();
    const tx = await wallet.writeContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "cancelWithdrawal",
      chain: null,
    });
    await this.publicClient.waitForTransactionReceipt({ hash: tx });
    return tx;
  }

  /** Submit a batch of signed receipts for settlement. */
  async settleBatch(receipts: SignedReceipt[]): Promise<SettlementResult> {
    const wallet = this.requireSigner();
    if (receipts.length === 0) throw new Error("Empty batch");

    const contractReceipts = receipts.map((sr) => ({
      receipt: {
        clientPaymentAddress: sr.receipt.clientPaymentAddress,
        nodeCollectionAddress: sr.receipt.nodeCollectionAddress,
        requestId: sr.receipt.requestId,
        dataBytes: sr.receipt.dataBytes,
        priceWei: sr.receipt.priceWei,
        timestamp: sr.receipt.timestamp,
      },
      signature: sr.signature,
    }));

    const tx = await wallet.writeContract({
      address: this.contractAddress,
      abi: ESCROW_ABI,
      functionName: "settleBatch",
      args: [contractReceipts],
      chain: null,
    });

    const receipt = await this.publicClient.waitForTransactionReceipt({ hash: tx });

    // Parse return values from transaction receipt events
    // For now, return tx hash and placeholder counts
    return {
      paid: BigInt(receipts.length),
      skipped: 0n,
      underfunded: 0n,
      txHash: tx,
    };
  }

  // ── EIP-712 Signing ────────────────────────────────────────────

  /** Sign a receipt using EIP-712. Returns signature hex. */
  async signReceipt(receipt: Receipt): Promise<Hex> {
    const wallet = this.requireSigner();

    // Use the wallet account to sign
    if (!this.walletClient) throw new Error("No wallet client");

    return await this.walletClient.signTypedData({
      domain: {
        ...RECEIPT_EIP712_DOMAIN,
        chainId: this.chainId,
        verifyingContract: this.contractAddress,
      },
      types: receiptTypes,
      primaryType: "Receipt",
      message: receipt,
      account: undefined as any, // Account is set on wallet client
    });
  }
}
