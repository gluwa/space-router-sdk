/**
 * Cross-stack canonical EIP-712 vector test.
 *
 * Source of truth: `internal-docs/v1.5-consumer-protocol.md` §7.
 *
 * The expected signature was emitted by the Python SDK and is the join point
 * between Python and JS implementations. Any drift here breaks the gateway's
 * signer-recovery step in production.
 */

import { describe, expect, it } from "vitest";
import {
  recoverReceiptSigner,
  signReceipt,
  type EIP712Domain,
  type Receipt,
} from "../src/payment/eip712.js";

const PRIVATE_KEY =
  "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937" as const;
const EXPECTED_ADDRESS = "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C" as const;
const EXPECTED_SIGNATURE =
  "0x15cbab3e32932fdfc01ebfb712b34ef1970f9b7b6e08318aea414ca1dbd4a2bf04d5812dda908013e42091ae473667dfbf6110432e1f4e3ee7b9543916c61dd41c" as const;

const DOMAIN: EIP712Domain = {
  name: "TokenPaymentEscrow",
  version: "1",
  chainId: 102031n,
  verifyingContract: "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
};

const RECEIPT: Receipt = {
  clientAddress: EXPECTED_ADDRESS,
  nodeAddress:
    "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
  requestUUID: "00000000-0000-0000-0000-000000000001",
  dataAmount: 1024n,
  totalPrice: 1_000_000_000_000_000n,
};

describe("EIP-712 canonical vector (protocol §7)", () => {
  it("signReceipt produces the byte-identical Python signature", async () => {
    const signature = await signReceipt(PRIVATE_KEY, RECEIPT, DOMAIN);
    expect(signature).toBe(EXPECTED_SIGNATURE);
  });

  it("signature is canonical 65-byte r||s||v with v ∈ {27, 28}", async () => {
    const signature = await signReceipt(PRIVATE_KEY, RECEIPT, DOMAIN);
    // 0x + 130 hex chars = 132 chars, last byte is v
    expect(signature.length).toBe(132);
    const v = parseInt(signature.slice(-2), 16);
    expect([27, 28]).toContain(v);
  });

  it("recoverReceiptSigner returns the expected address", async () => {
    const recovered = await recoverReceiptSigner(
      RECEIPT,
      EXPECTED_SIGNATURE,
      DOMAIN,
    );
    expect(recovered.toLowerCase()).toBe(EXPECTED_ADDRESS.toLowerCase());
  });

  it("accepts lowercase clientAddress and recovers the same signer", async () => {
    const lowercaseReceipt: Receipt = {
      ...RECEIPT,
      clientAddress: EXPECTED_ADDRESS.toLowerCase() as `0x${string}`,
    };
    const signature = await signReceipt(PRIVATE_KEY, lowercaseReceipt, DOMAIN);
    expect(signature).toBe(EXPECTED_SIGNATURE);
  });
});
