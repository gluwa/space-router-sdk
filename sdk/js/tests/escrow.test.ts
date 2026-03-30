/**
 * Tests for SpaceRouter EscrowClient (JS SDK).
 *
 * Unit tests using mocked viem clients.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock viem/accounts BEFORE importing EscrowClient
vi.mock("viem/accounts", () => ({
  privateKeyToAccount: vi.fn(() => ({
    address: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" as const,
  })),
}));

// Mock viem creation functions
vi.mock("viem", async () => {
  const actual = await vi.importActual("viem");
  return {
    ...actual,
    createPublicClient: vi.fn(() => ({
      readContract: vi.fn(),
      waitForTransactionReceipt: vi.fn(),
    })),
    createWalletClient: vi.fn(() => ({
      writeContract: vi.fn(),
      signTypedData: vi.fn(),
    })),
  };
});

import {
  EscrowClient,
  ESCROW_ABI,
  RECEIPT_EIP712_DOMAIN,
  receiptTypes,
  type EscrowClientOptions,
} from "../src/escrow.js";

describe("EscrowClient", () => {
  describe("EIP-712 Constants", () => {
    it("should have correct domain name", () => {
      expect(RECEIPT_EIP712_DOMAIN.name).toBe("SpaceRouterEscrow");
    });

    it("should have correct domain version", () => {
      expect(RECEIPT_EIP712_DOMAIN.version).toBe("1");
    });

    it("should define Receipt types with 6 fields", () => {
      expect(receiptTypes.Receipt).toHaveLength(6);
      expect(receiptTypes.Receipt[0].name).toBe("clientPaymentAddress");
    });

    it("should include all Receipt field types", () => {
      const names = receiptTypes.Receipt.map((f) => f.name);
      expect(names).toContain("clientPaymentAddress");
      expect(names).toContain("nodeCollectionAddress");
      expect(names).toContain("requestId");
      expect(names).toContain("dataBytes");
      expect(names).toContain("priceWei");
      expect(names).toContain("timestamp");
    });
  });

  describe("Constructor", () => {
    it("should create read-only client without private key", () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
      });
      expect(client.address).toBeNull();
    });

    it("should create writable client with private key", () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
        privateKey: "0xababababababababababababababababababababababababababababababababab",
      });
      expect(client.address).toBe("0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    });
  });

  describe("Write operations guard", () => {
    it("should throw when deposit called without private key", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
      });
      await expect(client.deposit(1000n)).rejects.toThrow("Private key required");
    });

    it("should throw when initiateWithdrawal called without private key", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
      });
      await expect(client.initiateWithdrawal(1000n)).rejects.toThrow("Private key required");
    });

    it("should throw when completeWithdrawal called without private key", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
      });
      await expect(client.completeWithdrawal()).rejects.toThrow("Private key required");
    });

    it("should throw on zero deposit amount", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
        privateKey: "0xababababababababababababababababababababababababababababababababab",
      });
      await expect(client.deposit(0n)).rejects.toThrow("positive");
    });

    it("should throw on zero withdrawal amount", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
        privateKey: "0xababababababababababababababababababababababababababababababababab",
      });
      await expect(client.initiateWithdrawal(0n)).rejects.toThrow("positive");
    });

    it("should throw on empty settle batch", async () => {
      const client = new EscrowClient({
        rpcUrl: "http://localhost:8545",
        contractAddress: "0x1111111111111111111111111111111111111111",
        chainId: 1,
        privateKey: "0xababababababababababababababababababababababababababababababababab",
      });
      await expect(client.settleBatch([])).rejects.toThrow("Empty batch");
    });
  });

  describe("ABI", () => {
    it("should be a non-empty array", () => {
      expect(Array.isArray(ESCROW_ABI)).toBe(true);
      expect(ESCROW_ABI.length).toBeGreaterThan(0);
    });
  });
});
