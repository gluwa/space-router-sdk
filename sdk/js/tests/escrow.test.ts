/**
 * `EscrowClient` unit tests.
 *
 * No live testnet hits — we stub `fetch` to capture the JSON-RPC request
 * payloads viem emits and assert each one is shaped correctly. Track D's
 * harness covers actual on-chain integration.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { encodeFunctionResult, keccak256, toBytes } from "viem";
import { EscrowClient } from "../src/escrow.js";
import { ERC20_ABI, ESCROW_ABI } from "../src/escrow.abi.js";

const RPC_URL = "https://rpc.example/v1";
const ESCROW_ADDR = "0xC5740e4e9175301a24FB6d22bA184b8ec0762852" as const;
const TOKEN_ADDR = "0x7395953AfBD4F33F05dBadCf32e045B3dd1a62FA" as const;
const PRIVATE_KEY =
  "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937" as const;
const ACCOUNT_ADDR = "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C" as const;

interface RpcCall {
  method: string;
  params: unknown[];
}

interface RpcHandler {
  (call: RpcCall): unknown;
}

function installRpcMock(handler: RpcHandler): {
  calls: RpcCall[];
  restore: () => void;
} {
  const calls: RpcCall[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (
    _input: string | URL | Request,
    init?: RequestInit,
  ): Promise<Response> => {
    const body = JSON.parse(init!.body as string);
    const wrapOne = (req: { id: number; method: string; params: unknown[] }) => {
      calls.push({ method: req.method, params: req.params });
      const result = handler({ method: req.method, params: req.params });
      return { jsonrpc: "2.0", id: req.id, result };
    };
    const payload = Array.isArray(body)
      ? body.map(wrapOne)
      : wrapOne(body);
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
  return { calls, restore: () => void (globalThis.fetch = original) };
}

let mock: { calls: RpcCall[]; restore: () => void } | null = null;

afterEach(() => {
  mock?.restore();
  mock = null;
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Read methods — verify call shapes match expected ABI selectors.
// ---------------------------------------------------------------------------

describe("EscrowClient reads", () => {
  beforeEach(() => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f"; // 102031
      if (call.method === "eth_call") {
        const tx = call.params[0] as { to: string; data: string };
        // ERC-20 balanceOf is 0x70a08231; escrow.getBalance is 0xf8b2cb4f.
        if (tx.data.startsWith("0x70a08231")) {
          return encodeFunctionResult({
            abi: ERC20_ABI,
            functionName: "balanceOf",
            result: 99_999n,
          });
        }
        if (tx.data.startsWith("0xf8b2cb4f")) {
          return encodeFunctionResult({
            abi: ESCROW_ABI,
            functionName: "getBalance",
            result: 12345n,
          });
        }
      }
      return "0x";
    });
  });

  it("balance() reads `getBalance` on the escrow contract", async () => {
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    const result = await client.balance(ACCOUNT_ADDR);
    expect(result).toBe(12345n);

    const calls = mock!.calls.filter((c) => c.method === "eth_call");
    expect(calls.length).toBeGreaterThanOrEqual(1);
    const tx = calls[0]!.params[0] as { to: string; data: string };
    expect(tx.to.toLowerCase()).toBe(ESCROW_ADDR.toLowerCase());
    expect(tx.data.startsWith("0xf8b2cb4f")).toBe(true); // getBalance(address)
  });

  it("tokenBalance() reads `balanceOf` on the token contract", async () => {
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    await client.tokenBalance(ACCOUNT_ADDR);
    const tx = mock!.calls.find((c) => c.method === "eth_call")!
      .params[0] as { to: string; data: string };
    expect(tx.to.toLowerCase()).toBe(TOKEN_ADDR.toLowerCase());
    expect(tx.data.startsWith("0x70a08231")).toBe(true);
  });
});

describe("EscrowClient.withdrawalRequest", () => {
  it("decodes (amount, readyAt) tuple from getWithdrawalRequest", async () => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_call") {
        return encodeFunctionResult({
          abi: ESCROW_ABI,
          functionName: "getWithdrawalRequest",
          result: [500n, 1_700_000_000n, true],
        });
      }
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    const wr = await client.withdrawalRequest(ACCOUNT_ADDR);
    expect(wr.amount).toBe(500n);
    expect(wr.readyAt).toBe(1_700_000_000n);
  });
});

describe("EscrowClient.isNonceUsed", () => {
  it("passes UUID string directly to isNonceUsed (contract hashes internally)", async () => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_call") {
        return encodeFunctionResult({
          abi: ESCROW_ABI,
          functionName: "isNonceUsed",
          result: true,
        });
      }
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    const uuid = "00000000-0000-0000-0000-000000000001";
    const used = await client.isNonceUsed(ACCOUNT_ADDR, uuid);
    expect(used).toBe(true);

    // Calldata embeds the UTF-8-encoded UUID string in the dynamic-args
    // section. Loose check: the lowercase hex of "00000000-0000-..." appears
    // as ASCII bytes in the calldata.
    const tx = mock!.calls.find((c) => c.method === "eth_call")!
      .params[0] as { to: string; data: string };
    const utf8Hex = Buffer.from(uuid, "utf8").toString("hex");
    expect(tx.data.toLowerCase()).toContain(utf8Hex);
  });
});

describe("EscrowClient.withdrawalDelay", () => {
  it("returns the on-chain WITHDRAWAL_DELAY constant", async () => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_call") {
        return encodeFunctionResult({
          abi: ESCROW_ABI,
          functionName: "WITHDRAWAL_DELAY",
          result: 432_000n,
        });
      }
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    expect(await client.withdrawalDelay()).toBe(432_000n);
  });
});

// ---------------------------------------------------------------------------
// Construction & guards
// ---------------------------------------------------------------------------

describe("EscrowClient construction", () => {
  it("rejects passing both privateKey and account", () => {
    expect(
      () =>
        new EscrowClient({
          rpcUrl: RPC_URL,
          contractAddress: ESCROW_ADDR,
          tokenAddress: TOKEN_ADDR,
          privateKey: PRIVATE_KEY,
          account: { address: ACCOUNT_ADDR, type: "json-rpc" } as unknown as never,
        }),
    ).toThrow(/either privateKey or account/);
  });

  it("read-only mode: address is null, writes throw", async () => {
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
    });
    expect(client.address).toBeNull();
    await expect(client.deposit(1n)).rejects.toThrow(/signer required/);
    await expect(client.executeWithdrawal()).rejects.toThrow(/signer required/);
    await expect(client.cancelWithdrawal()).rejects.toThrow(/signer required/);
  });

  it("write methods reject non-positive amounts", async () => {
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
      privateKey: PRIVATE_KEY,
    });
    await expect(client.deposit(0n)).rejects.toThrow(/positive/);
    await expect(client.initiateWithdrawal(-1n)).rejects.toThrow(/positive/);
    await expect(client.approve(0n)).rejects.toThrow(/positive/);
  });

  it("derives the bound signer address from the private key", () => {
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
      privateKey: PRIVATE_KEY,
    });
    expect(client.address).toBe(ACCOUNT_ADDR);
  });
});

// ---------------------------------------------------------------------------
// Write methods — sniff the eth_sendRawTransaction calldata.
// ---------------------------------------------------------------------------

describe("EscrowClient writes", () => {
  it("approve() targets the token contract with `approve` selector", async () => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_getTransactionCount") return "0x0";
      if (call.method === "eth_gasPrice") return "0x3b9aca00";
      if (call.method === "eth_estimateGas") return "0x186a0";
      if (call.method === "eth_maxPriorityFeePerGas") return "0x3b9aca00";
      if (call.method === "eth_getBlockByNumber") {
        return {
          baseFeePerGas: "0x3b9aca00",
          number: "0x1",
          hash: "0x" + "00".repeat(32),
          timestamp: "0x0",
        };
      }
      if (call.method === "eth_sendRawTransaction") {
        return "0x" + "ab".repeat(32);
      }
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
      privateKey: PRIVATE_KEY,
    });
    const hash = await client.approve(1000n);
    expect(hash).toMatch(/^0x(ab){32}$/);

    // Ensure the write call went out
    const sent = mock!.calls.filter(
      (c) => c.method === "eth_sendRawTransaction",
    );
    expect(sent.length).toBe(1);
  });

  it("initiateWithdrawal/executeWithdrawal/cancelWithdrawal all submit a tx", async () => {
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_getTransactionCount") return "0x0";
      if (call.method === "eth_gasPrice") return "0x3b9aca00";
      if (call.method === "eth_estimateGas") return "0x186a0";
      if (call.method === "eth_maxPriorityFeePerGas") return "0x3b9aca00";
      if (call.method === "eth_getBlockByNumber") {
        return {
          baseFeePerGas: "0x3b9aca00",
          number: "0x1",
          hash: "0x" + "00".repeat(32),
          timestamp: "0x0",
        };
      }
      if (call.method === "eth_sendRawTransaction") {
        return "0x" + "cd".repeat(32);
      }
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
      privateKey: PRIVATE_KEY,
    });
    expect(await client.initiateWithdrawal(1n)).toMatch(/^0x(cd){32}$/);
    expect(await client.executeWithdrawal()).toMatch(/^0x(cd){32}$/);
    expect(await client.cancelWithdrawal()).toMatch(/^0x(cd){32}$/);

    const sent = mock!.calls.filter(
      (c) => c.method === "eth_sendRawTransaction",
    );
    expect(sent.length).toBe(3);
  });

  it("deposit(autoApprove=true) sends approve first when allowance is short", async () => {
    let allowance = 0n;
    mock = installRpcMock((call) => {
      if (call.method === "eth_chainId") return "0x18e0f";
      if (call.method === "eth_getTransactionCount") return "0x0";
      if (call.method === "eth_gasPrice") return "0x3b9aca00";
      if (call.method === "eth_estimateGas") return "0x186a0";
      if (call.method === "eth_maxPriorityFeePerGas") return "0x3b9aca00";
      if (call.method === "eth_getBlockByNumber") {
        return {
          baseFeePerGas: "0x3b9aca00",
          number: "0x1",
          hash: "0x" + "00".repeat(32),
          timestamp: "0x0",
        };
      }
      if (call.method === "eth_call") {
        const tx = call.params[0] as { data: string };
        if (tx.data.startsWith("0xdd62ed3e")) {
          // allowance(owner, spender)
          return encodeFunctionResult({
            abi: ERC20_ABI,
            functionName: "allowance",
            result: allowance,
          });
        }
        return "0x";
      }
      if (call.method === "eth_sendRawTransaction") {
        // After approve lands, tests set allowance high enough; we don't
        // simulate ordering here — both txs share the same fake hash.
        allowance = 999n;
        return "0x" + "ef".repeat(32);
      }
      if (call.method === "eth_getTransactionReceipt") {
        return {
          status: "0x1",
          blockNumber: "0x1",
          blockHash: "0x" + "00".repeat(32),
          transactionHash: "0x" + "ef".repeat(32),
          transactionIndex: "0x0",
          from: ACCOUNT_ADDR.toLowerCase(),
          to: TOKEN_ADDR.toLowerCase(),
          contractAddress: null,
          logs: [],
          logsBloom: "0x" + "00".repeat(256),
          gasUsed: "0x186a0",
          cumulativeGasUsed: "0x186a0",
          effectiveGasPrice: "0x3b9aca00",
          type: "0x2",
        };
      }
      if (call.method === "eth_blockNumber") return "0x1";
      return "0x";
    });
    const client = new EscrowClient({
      rpcUrl: RPC_URL,
      contractAddress: ESCROW_ADDR,
      tokenAddress: TOKEN_ADDR,
      privateKey: PRIVATE_KEY,
    });
    await client.deposit(500n);

    const sends = mock!.calls.filter(
      (c) => c.method === "eth_sendRawTransaction",
    );
    // approve + deposit
    expect(sends.length).toBe(2);
  });
});
