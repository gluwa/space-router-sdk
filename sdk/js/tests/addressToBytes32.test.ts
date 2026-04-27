/**
 * `addressToBytes32` parity tests.
 *
 * Mirrors the Python `address_to_bytes32` helper: lowercases the input, then
 * left-pads with 24 zero bytes (12 zero-bytes = 24 hex chars).
 */

import { describe, expect, it } from "vitest";
import { addressToBytes32 } from "../src/payment/eip712.js";

describe("addressToBytes32", () => {
  it("lowercases and zero-pads a checksummed address", () => {
    const result = addressToBytes32(
      "0x9e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
    expect(result).toBe(
      "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
  });

  it("lowercases mixed-case input (Python parity)", () => {
    const result = addressToBytes32(
      "0x9E46051b44B1639A8A9f8A53041C6F121c0Fe789",
    );
    expect(result).toBe(
      "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
  });

  it("emits exactly 32 bytes (66-char 0x-prefixed string)", () => {
    const result = addressToBytes32(
      "0x9e46051b44b1639a8a9f8a53041c6f121c0fe789",
    );
    expect(result.length).toBe(66);
  });

  it("rejects non-20-byte addresses", () => {
    expect(() =>
      addressToBytes32("0x1234" as `0x${string}`),
    ).toThrow(/invalid 20-byte address/);
  });
});
