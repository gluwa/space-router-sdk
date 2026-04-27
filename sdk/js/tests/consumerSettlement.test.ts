/**
 * Tests for ConsumerSettlementClient using undici MockAgent.
 *
 * Covers:
 *   - GET /leg1/pending: signed query string, lowercase address, ts within ±60s
 *   - POST /leg1/sign: body shape, accepted/rejected parsing
 *   - strict mode throws SettlementRejectedError on rejected entries
 *   - non-strict swallows rejections
 *   - syncReceipts round-trip with mixed accept/reject
 *   - 503 → 503 → 200 retry policy
 *   - 4xx surfaces body verbatim
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { MockAgent, setGlobalDispatcher, getGlobalDispatcher } from "undici";
import type { Dispatcher } from "undici";

import { ConsumerSettlementClient } from "../src/payment/consumerSettlement.js";
import { ClientPaymentWallet } from "../src/payment/_track-c-stub.js";
import { SettlementRejectedError } from "../src/errors.js";

const PRIVATE_KEY =
  "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937" as const;
const EXPECTED_ADDRESS_LOWER = "0x61f5b13a42016d94adeac2857f77cc7cd9f0e11c";
const GATEWAY_HOST = "https://gateway-test.example";

const DOMAIN_WIRE = {
  name: "TokenPaymentEscrow",
  version: "1",
  chainId: 102031,
  verifyingContract: "0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
};

let agent: MockAgent;
let prevDispatcher: Dispatcher;

beforeEach(() => {
  prevDispatcher = getGlobalDispatcher();
  agent = new MockAgent();
  agent.disableNetConnect();
  setGlobalDispatcher(agent);
});

afterEach(async () => {
  await agent.close();
  setGlobalDispatcher(prevDispatcher);
});

function makeClient(): ConsumerSettlementClient {
  const wallet = new ClientPaymentWallet(PRIVATE_KEY);
  return new ConsumerSettlementClient({
    gatewayMgmtUrl: GATEWAY_HOST,
    wallet,
  });
}

// ---------------------------------------------------------------------------
// GET /leg1/pending
// ---------------------------------------------------------------------------

describe("ConsumerSettlementClient.fetchPending", () => {
  it("includes lowercase address, ts within ±60s, and 65-byte sig in query", async () => {
    const pool = agent.get(GATEWAY_HOST);
    let capturedPath: string | undefined;
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, (opts) => {
        capturedPath = opts.path;
        return {
          receipts: [],
          domain: DOMAIN_WIRE,
        };
      });

    const client = makeClient();
    const result = await client.fetchPending(25);

    expect(result.receipts).toEqual([]);
    expect(result.domain.chainId).toBe(102031);

    expect(capturedPath).toBeDefined();
    const url = new URL(`${GATEWAY_HOST}${capturedPath}`);
    expect(url.pathname).toBe("/leg1/pending");
    expect(url.searchParams.get("address")).toBe(EXPECTED_ADDRESS_LOWER);
    expect(url.searchParams.get("limit")).toBe("25");

    const ts = parseInt(url.searchParams.get("ts") ?? "0", 10);
    const now = Math.floor(Date.now() / 1000);
    expect(Math.abs(now - ts)).toBeLessThanOrEqual(60);

    const sig = url.searchParams.get("sig") ?? "";
    expect(sig).toMatch(/^0x[0-9a-f]{130}$/);
  });

  it("decodes wire receipts: snake_case → camelCase, uint256 → bigint", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, {
        receipts: [
          {
            request_uuid: "uuid-1",
            client_address: "0xABCDEF0000000000000000000000000000000001",
            node_address:
              "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
            data_amount: 1024,
            total_price: "1000000000000000",
            tunnel_request_id: "tun-1",
            created_at: "2026-04-27T10:00:00+00:00",
          },
        ],
        domain: DOMAIN_WIRE,
      });

    const client = makeClient();
    const { receipts } = await client.fetchPending();

    expect(receipts).toHaveLength(1);
    const r = receipts[0]!;
    expect(r.requestUUID).toBe("uuid-1");
    expect(r.clientAddress).toBe("0xabcdef0000000000000000000000000000000001");
    expect(r.dataAmount).toBe(1024n);
    expect(r.totalPrice).toBe(1000000000000000n);
    expect(typeof r.dataAmount).toBe("bigint");
    expect(typeof r.totalPrice).toBe("bigint");
  });
});

// ---------------------------------------------------------------------------
// POST /leg1/sign
// ---------------------------------------------------------------------------

describe("ConsumerSettlementClient.submitSignatures", () => {
  it("posts the expected body shape", async () => {
    const pool = agent.get(GATEWAY_HOST);
    let capturedBody: string | undefined;
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, (opts) => {
        capturedBody = String(opts.body ?? "");
        return { accepted: ["uuid-1"], rejected: [] };
      });

    const client = makeClient();
    const result = await client.submitSignatures([
      { requestUuid: "uuid-1", signature: "0xdeadbeef" as `0x${string}` },
    ]);

    expect(result.accepted).toEqual(["uuid-1"]);
    expect(result.rejected).toEqual([]);

    expect(capturedBody).toBeDefined();
    const parsed = JSON.parse(capturedBody!);
    expect(parsed.address).toBe(EXPECTED_ADDRESS_LOWER);
    expect(typeof parsed.ts).toBe("number");
    expect(parsed.sig).toMatch(/^0x[0-9a-f]{130}$/);
    expect(parsed.signatures).toEqual([
      { request_uuid: "uuid-1", signature: "0xdeadbeef" },
    ]);
  });

  it("parses accepted + rejected lists (camelCase mapping)", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, {
        accepted: ["uuid-1"],
        rejected: [{ request_uuid: "uuid-2", reason: "eip712_signer_mismatch" }],
      });

    const client = makeClient();
    const result = await client.submitSignatures([
      { requestUuid: "uuid-1", signature: "0xdead" as `0x${string}` },
      { requestUuid: "uuid-2", signature: "0xbeef" as `0x${string}` },
    ]);

    expect(result.accepted).toEqual(["uuid-1"]);
    expect(result.rejected).toEqual([
      { requestUuid: "uuid-2", reason: "eip712_signer_mismatch" },
    ]);
  });

  it("strict mode throws SettlementRejectedError when there are rejections", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, {
        accepted: [],
        rejected: [{ request_uuid: "uuid-1", reason: "not_pending" }],
      });

    const client = makeClient();
    await expect(
      client.submitSignatures(
        [{ requestUuid: "uuid-1", signature: "0xdead" as `0x${string}` }],
        { strict: true },
      ),
    ).rejects.toBeInstanceOf(SettlementRejectedError);
  });

  it("non-strict mode swallows rejections", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, {
        accepted: [],
        rejected: [{ request_uuid: "uuid-1", reason: "not_pending" }],
      });

    const client = makeClient();
    const result = await client.submitSignatures([
      { requestUuid: "uuid-1", signature: "0xdead" as `0x${string}` },
    ]);
    expect(result.rejected).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// syncReceipts
// ---------------------------------------------------------------------------

describe("ConsumerSettlementClient.syncReceipts", () => {
  it("round-trips fetch+sign+submit; mixed result does not throw in non-strict", async () => {
    const pool = agent.get(GATEWAY_HOST);

    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, {
        receipts: [
          {
            request_uuid: "uuid-1",
            client_address: "0x0000000000000000000000000000000000000001",
            node_address:
              "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
            data_amount: 1024,
            total_price: "1000000000000000",
          },
          {
            request_uuid: "uuid-2",
            client_address: "0x0000000000000000000000000000000000000002",
            node_address:
              "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
            data_amount: 2048,
            total_price: "2000000000000000",
          },
        ],
        domain: DOMAIN_WIRE,
      });

    let postBody: string | undefined;
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, (opts) => {
        postBody = String(opts.body ?? "");
        return {
          accepted: ["uuid-1"],
          rejected: [{ request_uuid: "uuid-2", reason: "not_pending" }],
        };
      });

    const client = makeClient();
    const result = await client.syncReceipts();
    expect(result.accepted).toEqual(["uuid-1"]);
    expect(result.rejected).toEqual([
      { requestUuid: "uuid-2", reason: "not_pending" },
    ]);

    const parsed = JSON.parse(postBody!);
    expect(parsed.signatures).toHaveLength(2);
    expect(parsed.signatures[0].request_uuid).toBe("uuid-1");
    expect(parsed.signatures[1].request_uuid).toBe("uuid-2");
    // Each entry is a full 65-byte EIP-712 sig.
    for (const s of parsed.signatures) {
      expect(s.signature).toMatch(/^0x[0-9a-f]{130}$/);
    }
  });

  it("returns empty result when pending queue is drained", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, { receipts: [], domain: DOMAIN_WIRE });

    const client = makeClient();
    const result = await client.syncReceipts();
    expect(result).toEqual({ accepted: [], rejected: [] });
  });
});

// ---------------------------------------------------------------------------
// Retry policy
// ---------------------------------------------------------------------------

describe("ConsumerSettlementClient retry policy", () => {
  it("retries 503 → 503 → 200 and succeeds on third attempt", async () => {
    const pool = agent.get(GATEWAY_HOST);

    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(503, "first")
      .times(1);
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(503, "second")
      .times(1);
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, { receipts: [], domain: DOMAIN_WIRE })
      .times(1);

    const client = makeClient();
    const result = await client.fetchPending();
    expect(result.receipts).toEqual([]);
  }, 15000);

  it("4xx surfaces body verbatim", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(400, "bad-signature: ts skew too large");

    const client = makeClient();
    await expect(client.fetchPending()).rejects.toThrow(
      /bad-signature: ts skew too large/,
    );
  });
});
