/**
 * On-chain ABIs used by the v1.5 consumer SDK.
 *
 * These are inline TS const-asserted ABIs (viem-compatible). They mirror the
 * Python SDK's `escrow_abi.json`, but expose ONLY the methods consumers need.
 * See `internal-docs/v1.5-consumer-protocol.md` §6 for the authoritative list.
 */

export const ESCROW_ABI = [
  // ── Reads ─────────────────────────────────────────────────────────────
  // Method names mirror the deployed TokenPaymentEscrow.sol exactly.
  // (The protocol doc §6 used aliases — the Python SDK's escrow_abi.json
  // is the authoritative reference.)
  {
    type: "function",
    name: "getBalance",
    stateMutability: "view",
    inputs: [{ name: "client", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "getWithdrawalRequest",
    stateMutability: "view",
    inputs: [{ name: "client", type: "address" }],
    outputs: [
      { name: "amount", type: "uint256" },
      { name: "unlockAt", type: "uint256" },
      { name: "exists", type: "bool" },
    ],
  },
  {
    // Real contract takes the UUID string directly (hashes internally).
    type: "function",
    name: "isNonceUsed",
    stateMutability: "view",
    inputs: [
      { name: "client", type: "address" },
      { name: "requestUUID", type: "string" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
  {
    type: "function",
    name: "WITHDRAWAL_DELAY",
    stateMutability: "view",
    inputs: [],
    outputs: [{ name: "", type: "uint256" }],
  },
  // ── Writes ────────────────────────────────────────────────────────────
  {
    type: "function",
    name: "deposit",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "initiateWithdrawal",
    stateMutability: "nonpayable",
    inputs: [{ name: "amount", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "executeWithdrawal",
    stateMutability: "nonpayable",
    inputs: [],
    outputs: [],
  },
  {
    type: "function",
    name: "cancelWithdrawal",
    stateMutability: "nonpayable",
    inputs: [],
    outputs: [],
  },
] as const;

export const ERC20_ABI = [
  {
    type: "function",
    name: "balanceOf",
    stateMutability: "view",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "allowance",
    stateMutability: "view",
    inputs: [
      { name: "owner", type: "address" },
      { name: "spender", type: "address" },
    ],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "approve",
    stateMutability: "nonpayable",
    inputs: [
      { name: "spender", type: "address" },
      { name: "amount", type: "uint256" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
  {
    type: "function",
    name: "decimals",
    stateMutability: "view",
    inputs: [],
    outputs: [{ name: "", type: "uint8" }],
  },
] as const;
