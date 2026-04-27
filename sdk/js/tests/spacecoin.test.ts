/**
 * Tests for SpaceRouterSPACE façade using undici MockAgent.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { MockAgent, setGlobalDispatcher, getGlobalDispatcher } from "undici";
import type { Dispatcher } from "undici";

import { SpaceRouterSPACE } from "../src/payment/spacecoin.js";
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

function makeSpace(opts?: { strict?: boolean }): SpaceRouterSPACE {
  const wallet = new ClientPaymentWallet(PRIVATE_KEY);
  return new SpaceRouterSPACE({
    gatewayMgmtUrl: GATEWAY_HOST,
    wallet,
    strict: opts?.strict,
  });
}

describe("SpaceRouterSPACE.requestChallenge", () => {
  it("parses {challenge} from /auth/challenge", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "abc-123" });

    const space = makeSpace();
    expect(await space.requestChallenge()).toBe("abc-123");
  });

  it("rejects when challenge field missing or empty", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "" });

    const space = makeSpace();
    await expect(space.requestChallenge()).rejects.toThrow(/missing\/invalid challenge/);
  });

  it("surfaces non-2xx body verbatim", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(429, "rate-limited: try later");

    const space = makeSpace();
    await expect(space.requestChallenge()).rejects.toThrow(/rate-limited: try later/);
  });
});

describe("SpaceRouterSPACE.buildAuthHeaders", () => {
  it("delegates to wallet and includes the four X-SpaceRouter-* headers", async () => {
    const space = makeSpace();
    const h = await space.buildAuthHeaders("test-challenge-xyz");
    expect(h["X-SpaceRouter-Payment-Address"]).toBe(EXPECTED_ADDRESS_LOWER);
    expect(h["X-SpaceRouter-Identity-Address"]).toBe(EXPECTED_ADDRESS_LOWER);
    expect(h["X-SpaceRouter-Challenge"]).toBe("test-challenge-xyz");
    expect(h["X-SpaceRouter-Challenge-Signature"]).toMatch(/^0x[0-9a-f]{130}$/);
  });
});

describe("SpaceRouterSPACE.validateReceipt", () => {
  it("rejects non-bigint amounts", () => {
    const space = makeSpace();
    expect(() =>
      space.validateReceipt(
        {
          clientAddress: "0xabc" as `0x${string}`,
          nodeAddress:
            "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789",
          requestUUID: "u",
          // @ts-expect-error -- intentionally invalid
          dataAmount: 1024,
          totalPrice: 1n,
        },
        {
          name: "x",
          version: "1",
          chainId: 1,
          verifyingContract: "0x0000000000000000000000000000000000000000",
        },
      ),
    ).toThrow(/dataAmount must be bigint/);
  });
});

describe("SpaceRouterSPACE.syncReceipts", () => {
  it("delegates to ConsumerSettlementClient and propagates non-strict", async () => {
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
        ],
        domain: DOMAIN_WIRE,
      });
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, {
        accepted: [],
        rejected: [{ request_uuid: "uuid-1", reason: "not_pending" }],
      });

    const space = makeSpace();
    const result = await space.syncReceipts();
    expect(result.rejected).toHaveLength(1);
  });

  it("propagates strict to the underlying client (raises)", async () => {
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
        ],
        domain: DOMAIN_WIRE,
      });
    pool
      .intercept({ path: "/leg1/sign", method: "POST" })
      .reply(200, {
        accepted: [],
        rejected: [{ request_uuid: "uuid-1", reason: "not_pending" }],
      });

    const space = makeSpace({ strict: true });
    await expect(space.syncReceipts()).rejects.toBeInstanceOf(SettlementRejectedError);
  });
});
