import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { existsSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

import { ClientIdentity, loadOrCreateIdentity } from "../src/identity.js";

const TEST_KEY = ("0x" + "ab".repeat(32)) as `0x${string}`;

let testDir: string;

beforeEach(() => {
  testDir = join(tmpdir(), `spacerouter-test-${randomBytes(8).toString("hex")}`);
  mkdirSync(testDir, { recursive: true });
});

afterEach(() => {
  rmSync(testDir, { recursive: true, force: true });
});

describe("ClientIdentity", () => {
  describe("factory methods", () => {
    it("fromPrivateKey creates identity with correct address", () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      expect(identity.address).toMatch(/^0x[0-9a-f]{40}$/);
    });

    it("generate creates a new unique identity", () => {
      const id1 = ClientIdentity.generate();
      const id2 = ClientIdentity.generate();
      expect(id1.address).not.toBe(id2.address);
    });

    it("generate with keystorePath saves to disk", () => {
      const path = join(testDir, "identity.key");
      const identity = ClientIdentity.generate(path);
      expect(existsSync(path)).toBe(true);
      expect(identity.address).toMatch(/^0x[0-9a-f]{40}$/);
    });

    it("fromKeystore loads from plaintext file", () => {
      const path = join(testDir, "identity.key");
      writeFileSync(path, TEST_KEY + "\n");
      const identity = ClientIdentity.fromKeystore(path);
      const directIdentity = ClientIdentity.fromPrivateKey(TEST_KEY);
      expect(identity.address).toBe(directIdentity.address);
    });
  });

  describe("signing", () => {
    it("signMessage produces valid EIP-191 signature", async () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      const sig = await identity.signMessage("hello world");
      expect(sig).toMatch(/^0x[0-9a-f]+$/);
    });

    it("signAuthHeaders returns correct header shape", async () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      const headers = await identity.signAuthHeaders();
      expect(headers).toHaveProperty("X-Identity-Address");
      expect(headers).toHaveProperty("X-Identity-Signature");
      expect(headers).toHaveProperty("X-Timestamp");
      expect(headers["X-Identity-Address"]).toBe(identity.address);
    });

    it("signAuthHeaders uses provided timestamp", async () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      const headers = await identity.signAuthHeaders(1234567890);
      expect(headers["X-Timestamp"]).toBe("1234567890");
    });

    it("signAuthHeaders timestamp is recent", async () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      const headers = await identity.signAuthHeaders();
      const ts = parseInt(headers["X-Timestamp"], 10);
      const now = Math.floor(Date.now() / 1000);
      expect(Math.abs(ts - now)).toBeLessThan(5);
    });
  });

  describe("payment address", () => {
    it("defaults to undefined", () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      expect(identity.paymentAddress).toBeUndefined();
    });

    it("can be set and normalizes to lowercase", () => {
      const identity = ClientIdentity.fromPrivateKey(TEST_KEY);
      identity.paymentAddress = "0xABCD1234567890ABCDEF1234567890ABCDEF1234";
      expect(identity.paymentAddress).toBe(
        "0xabcd1234567890abcdef1234567890abcdef1234",
      );
    });
  });

  describe("keystore", () => {
    it("save and load roundtrip", () => {
      const path = join(testDir, "identity.key");
      const original = ClientIdentity.fromPrivateKey(TEST_KEY);
      original.saveKeystore(path);
      const loaded = ClientIdentity.fromKeystore(path);
      expect(loaded.address).toBe(original.address);
    });

    it("generate and reload produce same address", () => {
      const path = join(testDir, "identity.key");
      const original = ClientIdentity.generate(path);
      const loaded = ClientIdentity.fromKeystore(path);
      expect(loaded.address).toBe(original.address);
    });
  });
});
