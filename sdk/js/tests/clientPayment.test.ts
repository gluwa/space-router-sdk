/**
 * Tests for v0.2.3 JavaScript SDK client payment modules.
 *
 * Covers:
 * - ClientWallet (challenge signing, receipt signing)
 * - ReceiptValidator (all 5 checks + timestamp)
 * - SpaceRouterSPACE (frame encoding/decoding)
 */

import { describe, it, expect, beforeEach } from "vitest";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import type { Address, Hex } from "viem";

import { ClientWallet } from "../src/payment/clientWallet.js";
import { ReceiptValidator, type ReceiptData } from "../src/payment/receiptValidator.js";
import { SpaceRouterSPACE } from "../src/spacerouterSpace.js";
import type { Receipt } from "../src/escrow.js";

// ── Helpers ──────────────────────────────────────────────────────

function randomAddress(): Address {
  const bytes = Array.from({ length: 20 }, () =>
    Math.floor(Math.random() * 256).toString(16).padStart(2, "0"),
  ).join("");
  return `0x${bytes}` as Address;
}

function randomBytes16(): Hex {
  const bytes = Array.from({ length: 16 }, () =>
    Math.floor(Math.random() * 256).toString(16).padStart(2, "0"),
  ).join("");
  return `0x${bytes}` as Hex;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

// ── ClientWallet Tests ───────────────────────────────────────────

describe("ClientWallet", () => {
  let privateKey: Hex;
  let wallet: ClientWallet;
  let escrowContract: Address;

  beforeEach(() => {
    privateKey = generatePrivateKey();
    escrowContract = randomAddress();
    wallet = new ClientWallet({
      privateKey,
      chainId: 102031,
      escrowContract,
    });
  });

  it("should have a lowercase address", () => {
    expect(wallet.address).toMatch(/^0x[0-9a-f]{40}$/);
  });

  it("should have a checksummed address", () => {
    expect(wallet.checksumAddress).toMatch(/^0x[0-9a-fA-F]{40}$/);
  });

  it("should sign a challenge", async () => {
    const sig = await wallet.signChallenge("test_challenge_123");
    expect(sig).toMatch(/^0x[0-9a-f]+$/);
    expect(sig.length).toBeGreaterThan(10);
  });

  it("should produce different signatures for different challenges", async () => {
    const sig1 = await wallet.signChallenge("challenge_1");
    const sig2 = await wallet.signChallenge("challenge_2");
    expect(sig1).not.toBe(sig2);
  });

  it("should sign a receipt", async () => {
    const receipt: Receipt = {
      clientPaymentAddress: wallet.checksumAddress,
      nodeCollectionAddress: randomAddress(),
      requestId: randomBytes16(),
      dataBytes: 1024n,
      priceWei: 100n,
      timestamp: BigInt(nowSeconds()),
    };
    const sig = await wallet.signReceipt(receipt);
    expect(sig).toMatch(/^0x[0-9a-f]+$/);
  });

  it("should throw when signing receipt without escrow contract", async () => {
    const walletNoEscrow = new ClientWallet({
      privateKey,
      chainId: 102031,
    });
    const receipt: Receipt = {
      clientPaymentAddress: walletNoEscrow.checksumAddress,
      nodeCollectionAddress: randomAddress(),
      requestId: randomBytes16(),
      dataBytes: 1024n,
      priceWei: 100n,
      timestamp: BigInt(nowSeconds()),
    };
    await expect(walletNoEscrow.signReceipt(receipt)).rejects.toThrow(
      "Escrow contract address required",
    );
  });

  it("should produce different signatures from different wallets", async () => {
    const wallet2 = new ClientWallet({
      privateKey: generatePrivateKey(),
      chainId: 102031,
      escrowContract,
    });
    const challenge = "same_challenge";
    const sig1 = await wallet.signChallenge(challenge);
    const sig2 = await wallet2.signChallenge(challenge);
    expect(sig1).not.toBe(sig2);
  });
});

// ── ReceiptValidator Tests ───────────────────────────────────────

describe("ReceiptValidator", () => {
  let clientAddress: string;
  let validator: ReceiptValidator;

  beforeEach(() => {
    const pk = generatePrivateKey();
    const account = privateKeyToAccount(pk);
    clientAddress = account.address.toLowerCase();
    validator = new ReceiptValidator({
      clientAddress,
      maxRatePerGbWei: 1_000_000_000_000_000_000n, // 1 SPACE/GB
    });
  });

  function validReceipt(): ReceiptData {
    return {
      clientPaymentAddress: clientAddress,
      nodeCollectionAddress: randomAddress(),
      requestId: crypto.randomUUID(),
      dataBytes: 1024,
      priceWei: 100,
      timestamp: nowSeconds(),
    };
  }

  it("should accept a valid receipt", () => {
    const result = validator.validate(validReceipt());
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("should reject wrong client address", () => {
    const receipt = validReceipt();
    receipt.clientPaymentAddress = randomAddress();
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("mismatch"))).toBe(true);
  });

  it("should reject zero node address", () => {
    const receipt = validReceipt();
    receipt.nodeCollectionAddress = "0x" + "0".repeat(40);
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.toLowerCase().includes("zero"))).toBe(true);
  });

  it("should reject empty request ID", () => {
    const receipt = validReceipt();
    receipt.requestId = "";
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("Request ID"))).toBe(true);
  });

  it("should reject negative data bytes", () => {
    const receipt = validReceipt();
    receipt.dataBytes = -1;
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.toLowerCase().includes("negative"))).toBe(true);
  });

  it("should reject excessive price", () => {
    const receipt = validReceipt();
    receipt.dataBytes = 1024; // 1 KB
    receipt.priceWei = 10n ** 18n; // 1 SPACE for 1 KB — way too much
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("exceeds maximum"))).toBe(true);
  });

  it("should reject old timestamp", () => {
    const receipt = validReceipt();
    receipt.timestamp = nowSeconds() - 600; // 10 minutes ago
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("Timestamp drift"))).toBe(true);
  });

  it("should reject future timestamp", () => {
    const receipt = validReceipt();
    receipt.timestamp = nowSeconds() + 600; // 10 minutes in future
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes("Timestamp drift"))).toBe(true);
  });

  it("should accept any price when maxRatePerGbWei is 0", () => {
    const noLimitValidator = new ReceiptValidator({
      clientAddress,
      maxRatePerGbWei: 0n,
    });
    const receipt = validReceipt();
    receipt.priceWei = 10n ** 18n;
    const result = noLimitValidator.validate(receipt);
    expect(result.valid).toBe(true);
  });

  it("should collect multiple errors", () => {
    const receipt: ReceiptData = {
      clientPaymentAddress: randomAddress(),
      nodeCollectionAddress: "",
      requestId: "",
      dataBytes: -1,
      priceWei: -1,
      timestamp: 0,
    };
    const result = validator.validate(receipt);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThanOrEqual(4);
  });
});

// ── SpaceRouterSPACE Frame Tests ─────────────────────────────────

describe("SpaceRouterSPACE", () => {
  describe("readReceiptFrame", () => {
    it("should parse a valid receipt frame", () => {
      const receipt = {
        clientPaymentAddress: randomAddress(),
        nodeCollectionAddress: randomAddress(),
        requestId: crypto.randomUUID(),
        dataBytes: 1024,
        priceWei: 100,
        timestamp: nowSeconds(),
      };
      const payload = new TextEncoder().encode(JSON.stringify(receipt));
      const frame = new Uint8Array(4 + payload.length);
      const view = new DataView(frame.buffer);
      view.setUint32(0, payload.length, false);
      frame.set(payload, 4);

      const parsed = SpaceRouterSPACE.readReceiptFrame(frame);
      expect(parsed).not.toBeNull();
      expect(parsed!.dataBytes).toBe(1024);
    });

    it("should return null for too-short data", () => {
      expect(SpaceRouterSPACE.readReceiptFrame(new Uint8Array([0, 0]))).toBeNull();
    });

    it("should return null for incomplete frame", () => {
      const payload = new TextEncoder().encode('{"test": 1}');
      const frame = new Uint8Array(4 + payload.length);
      const view = new DataView(frame.buffer);
      view.setUint32(0, payload.length + 100, false); // Length too long
      frame.set(payload, 4);
      expect(SpaceRouterSPACE.readReceiptFrame(frame)).toBeNull();
    });
  });

  describe("encodeSignatureFrame", () => {
    it("should encode a signature frame", () => {
      const frame = SpaceRouterSPACE.encodeSignatureFrame("0xabc123");
      const view = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
      const length = view.getUint32(0, false);
      const payload = JSON.parse(new TextDecoder().decode(frame.slice(4, 4 + length)));
      expect(payload.signature).toBe("0xabc123");
    });

    it("should roundtrip correctly", () => {
      const sig = "0x" + "ab".repeat(65);
      const frame = SpaceRouterSPACE.encodeSignatureFrame(sig);
      const view = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
      const length = view.getUint32(0, false);
      const payload = JSON.parse(new TextDecoder().decode(frame.slice(4, 4 + length)));
      expect(payload.signature).toBe(sig);
    });
  });

  describe("constructor", () => {
    it("should create with valid options", () => {
      const client = new SpaceRouterSPACE({
        gatewayUrl: "http://localhost:8081",
        proxyUrl: "http://localhost:8080",
        privateKey: generatePrivateKey(),
        chainId: 102031,
        escrowContract: randomAddress(),
      });
      expect(client.address).toMatch(/^0x[0-9a-f]{40}$/);
    });
  });

  describe("validateReceipt", () => {
    it("should validate a receipt", () => {
      const privateKey = generatePrivateKey();
      const account = privateKeyToAccount(privateKey);
      const client = new SpaceRouterSPACE({
        gatewayUrl: "http://localhost:8081",
        proxyUrl: "http://localhost:8080",
        privateKey,
      });

      const receipt: ReceiptData = {
        clientPaymentAddress: account.address.toLowerCase(),
        nodeCollectionAddress: randomAddress(),
        requestId: crypto.randomUUID(),
        dataBytes: 1024,
        priceWei: 100,
        timestamp: nowSeconds(),
      };

      const result = client.validateReceipt(receipt);
      expect(result.valid).toBe(true);
    });
  });
});
