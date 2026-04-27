/**
 * `ClientPaymentWallet` unit tests.
 *
 * Verifies the four `X-SpaceRouter-*` headers, EIP-191 challenge signing,
 * and `verifyReceiptSignature` round-trip.
 */

import { describe, expect, it } from "vitest";
import { ClientPaymentWallet } from "../src/payment/clientWallet.js";
import type { EIP712Domain, Receipt } from "../src/payment/eip712.js";

const PRIVATE_KEY =
  "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937" as const;
const EXPECTED_ADDRESS_LOWER =
  "0x61f5b13a42016d94adeac2857f77cc7cd9f0e11c" as const;

const DOMAIN: EIP712Domain = {
  name: "TokenPaymentEscrow",
  version: "1",
  chainId: 102031n,
  verifyingContract: "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
};

const RECEIPT: Receipt = {
  clientAddress: "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C",
  nodeAddress:
    "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
  requestUUID: "00000000-0000-0000-0000-000000000001",
  dataAmount: 1024n,
  totalPrice: 1_000_000_000_000_000n,
};

describe("ClientPaymentWallet", () => {
  it("exposes lowercase wire-format address", () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    expect(wallet.address).toBe(EXPECTED_ADDRESS_LOWER);
  });

  it("rejects empty private key", () => {
    expect(() => new ClientPaymentWallet("" as `0x${string}`)).toThrow(
      /Private key is required/,
    );
  });

  it("signChallenge returns a 65-byte hex string", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    const sig = await wallet.signChallenge("opaque-challenge-abc123");
    // 0x + 130 hex chars
    expect(sig).toMatch(/^0x[0-9a-f]{130}$/);
    expect(sig.length).toBe(132);
  });

  it("buildAuthHeaders returns the four X-SpaceRouter-* headers", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    const headers = await wallet.buildAuthHeaders("opaque-challenge-abc123");

    expect(Object.keys(headers).sort()).toEqual([
      "X-SpaceRouter-Challenge",
      "X-SpaceRouter-Challenge-Signature",
      "X-SpaceRouter-Identity-Address",
      "X-SpaceRouter-Payment-Address",
    ]);
    expect(headers["X-SpaceRouter-Payment-Address"]).toBe(
      EXPECTED_ADDRESS_LOWER,
    );
    expect(headers["X-SpaceRouter-Identity-Address"]).toBe(
      EXPECTED_ADDRESS_LOWER,
    );
    expect(headers["X-SpaceRouter-Challenge"]).toBe("opaque-challenge-abc123");
    expect(headers["X-SpaceRouter-Challenge-Signature"]).toMatch(
      /^0x[0-9a-f]{130}$/,
    );
  });

  it("verifyReceiptSignature returns true for the wallet's own signature", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    const sig = await wallet.signReceipt(RECEIPT, DOMAIN);
    const ok = await ClientPaymentWallet.verifyReceiptSignature(
      RECEIPT,
      sig,
      DOMAIN,
      wallet.address,
    );
    expect(ok).toBe(true);
  });

  it("verifyReceiptSignature returns false for a wrong-signer expectation", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    const sig = await wallet.signReceipt(RECEIPT, DOMAIN);
    const ok = await ClientPaymentWallet.verifyReceiptSignature(
      RECEIPT,
      sig,
      DOMAIN,
      "0x0000000000000000000000000000000000000001",
    );
    expect(ok).toBe(false);
  });

  it("verifyReceiptSignature returns false on garbage signature", async () => {
    const garbage = `0x${"00".repeat(65)}` as `0x${string}`;
    const ok = await ClientPaymentWallet.verifyReceiptSignature(
      RECEIPT,
      garbage,
      DOMAIN,
      EXPECTED_ADDRESS_LOWER,
    );
    expect(ok).toBe(false);
  });
});
