/**
 * Sanity check that the Track-C stub matches the canonical EIP-712 vector
 * from `internal-docs/v1.5-consumer-protocol.md` §7.  If this fails the
 * stub diverges from the protocol contract and Python/JS won't interop.
 */

import { describe, it, expect } from "vitest";
import {
  addressToBytes32,
  signReceipt,
  ClientPaymentWallet,
  type EIP712Domain,
  type Receipt,
} from "../src/payment/_track-c-stub.js";

const PRIVATE_KEY =
  "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937" as const;
const EXPECTED_ADDRESS_LOWER = "0x61f5b13a42016d94adeac2857f77cc7cd9f0e11c";
const EXPECTED_SIGNATURE =
  "0x15cbab3e32932fdfc01ebfb712b34ef1970f9b7b6e08318aea414ca1dbd4a2bf04d5812dda908013e42091ae473667dfbf6110432e1f4e3ee7b9543916c61dd41c";

const DOMAIN: EIP712Domain = {
  name: "TokenPaymentEscrow",
  version: "1",
  chainId: 102031,
  verifyingContract: "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
};

const RECEIPT: Receipt = {
  clientAddress: "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C",
  nodeAddress:
    "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
  requestUUID: "00000000-0000-0000-0000-000000000001",
  dataAmount: 1024n,
  totalPrice: 1000000000000000n,
};

describe("track-c stub: canonical EIP-712 vector", () => {
  it("addressToBytes32 zero-pads + lowercases", () => {
    expect(addressToBytes32("0x9e46051b44b1639a8a9f8a53041c6f121c0fe789")).toBe(
      "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
    expect(addressToBytes32("0x9E46051B44B1639A8A9F8A53041C6F121C0FE789")).toBe(
      "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
  });

  it("signReceipt matches the canonical vector exactly", async () => {
    const sig = await signReceipt(PRIVATE_KEY, RECEIPT, DOMAIN);
    expect(sig).toBe(EXPECTED_SIGNATURE);
  });

  it("ClientPaymentWallet.signReceipt matches the canonical vector", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    expect(wallet.address).toBe(EXPECTED_ADDRESS_LOWER);
    const sig = await wallet.signReceipt(RECEIPT, DOMAIN);
    expect(sig).toBe(EXPECTED_SIGNATURE);
  });

  it("ClientPaymentWallet.buildAuthHeaders returns the four X-SpaceRouter-* headers", async () => {
    const wallet = new ClientPaymentWallet(PRIVATE_KEY);
    const headers = await wallet.buildAuthHeaders("test-challenge-123");
    expect(headers["X-SpaceRouter-Payment-Address"]).toBe(EXPECTED_ADDRESS_LOWER);
    expect(headers["X-SpaceRouter-Identity-Address"]).toBe(EXPECTED_ADDRESS_LOWER);
    expect(headers["X-SpaceRouter-Challenge"]).toBe("test-challenge-123");
    expect(headers["X-SpaceRouter-Challenge-Signature"]).toMatch(/^0x[0-9a-f]{130}$/);
  });
});
