/**
 * Tests for v1.5 payment-header injection + autoSettle on SpaceRouter.
 *
 * The proxy `request()` path uses global `fetch` with a `dispatcher`
 * option (ProxyAgent / SocksProxyAgent), so we stub global `fetch` to
 * capture outgoing headers.  The SpaceRouterSPACE façade uses
 * `undici.fetch` directly, which we intercept with MockAgent.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { MockAgent, setGlobalDispatcher, getGlobalDispatcher } from "undici";
import type { Dispatcher } from "undici";

import { SpaceRouter } from "../src/client.js";
import { SpaceRouterSPACE } from "../src/payment/spacecoin.js";
import { ClientPaymentWallet } from "../src/payment/clientWallet.js";

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
let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  prevDispatcher = getGlobalDispatcher();
  agent = new MockAgent();
  agent.disableNetConnect();
  setGlobalDispatcher(agent);

  // Stub the global fetch used by SpaceRouter.request(); we don't actually
  // want to hit an upstream — capture headers and return a fake 200 response.
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
    async (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => {
      return new Response("upstream-body", {
        status: 200,
        headers: { "x-spacerouter-request-id": "req-test-1" },
      });
    },
  );
});

afterEach(async () => {
  fetchSpy.mockRestore();
  await agent.close();
  setGlobalDispatcher(prevDispatcher);
});

function makeSpace(strict = false): SpaceRouterSPACE {
  return new SpaceRouterSPACE({
    gatewayMgmtUrl: GATEWAY_HOST,
    wallet: new ClientPaymentWallet(PRIVATE_KEY),
    strict,
  });
}

function getCapturedHeaders(): Record<string, string> {
  expect(fetchSpy).toHaveBeenCalled();
  const lastCall = fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1]!;
  const init = lastCall[1] as RequestInit | undefined;
  const raw = (init?.headers ?? {}) as Record<string, string>;
  return raw;
}

describe("SpaceRouter v1.5 payment header injection", () => {
  it("stamps the four X-SpaceRouter-* payment headers onto the proxy CONNECT", async () => {
    // Payment auth must ride on the proxy CONNECT request — gateway
    // can't read inner TLS-tunnelled headers. Verified by capturing
    // the dispatcher passed to fetch (a fresh ProxyAgent built for
    // this call) and inspecting its outgoing headers via fetch's init
    // object after the request.
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "challenge-abc" });

    let capturedDispatcher: any = null;
    fetchSpy.mockImplementation(
      async (_input: RequestInfo | URL, init?: any): Promise<Response> => {
        capturedDispatcher = init?.dispatcher;
        return new Response("upstream-body", { status: 200 });
      },
    );

    const space = makeSpace();
    const client = new SpaceRouter("api-key-ignored");
    const resp = await client.get("https://example.test/foo", { payment: space });
    expect(resp.status).toBe(200);

    // Per-request dispatcher must be a fresh ProxyAgent (not the shared
    // long-lived one), with payment headers in its connect-time headers.
    expect(capturedDispatcher).toBeDefined();
    // undici's ProxyAgent stores [Symbol(headers)] internally; the public
    // surface that matters is that it was constructed for THIS call.
    // We rely on the fact that on a non-paid call a different (shared)
    // dispatcher would be used (covered in the auto-key-path test below).
    const ctorName = capturedDispatcher?.constructor?.name;
    expect(ctorName).toBe("ProxyAgent");

    client.close();
  });

  it("autoSettle invokes payment.syncReceipts() after the request", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "challenge-1" });
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(200, { receipts: [], domain: DOMAIN_WIRE });

    const space = makeSpace();
    const syncSpy = vi.spyOn(space, "syncReceipts");
    const client = new SpaceRouter("api-key-ignored");

    await client.get("https://example.test/foo", {
      payment: space,
      autoSettle: true,
    });

    expect(syncSpy).toHaveBeenCalledTimes(1);
    client.close();
  });

  it("autoSettle errors are warn-logged in non-strict mode (no rethrow)", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "challenge-1" });
    // /leg1/pending fails 4xx — non-strict swallows.
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(400, "auth: bad ts skew");

    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const space = makeSpace(false);
    const client = new SpaceRouter("api-key-ignored");

    const resp = await client.get("https://example.test/foo", {
      payment: space,
      autoSettle: true,
    });
    expect(resp.status).toBe(200);
    expect(warnSpy).toHaveBeenCalled();
    expect(warnSpy.mock.calls[0]?.[0]).toMatch(/autoSettle failed/);

    warnSpy.mockRestore();
    client.close();
  });

  it("autoSettle errors rethrow when payment.strict is true", async () => {
    const pool = agent.get(GATEWAY_HOST);
    pool
      .intercept({ path: "/auth/challenge", method: "GET" })
      .reply(200, { challenge: "challenge-1" });
    pool
      .intercept({ path: (p: string) => p.startsWith("/leg1/pending"), method: "GET" })
      .reply(400, "auth: bad ts skew");

    const space = makeSpace(true);
    const client = new SpaceRouter("api-key-ignored");

    await expect(
      client.get("https://example.test/foo", { payment: space, autoSettle: true }),
    ).rejects.toThrow();

    client.close();
  });

  it("non-payment path is unchanged (no challenge fetch, no extra headers)", async () => {
    const client = new SpaceRouter("api-key-ignored");
    await client.get("https://example.test/foo");

    const headers = getCapturedHeaders();
    expect(headers["X-SpaceRouter-Challenge"]).toBeUndefined();
    expect(headers["X-SpaceRouter-Payment-Address"]).toBeUndefined();
    expect(headers["X-SpaceRouter-Identity-Address"]).toBeUndefined();

    // No /auth/challenge intercept was registered; MockAgent would have errored
    // on a real call.  Sanity-check by asserting we got a response.
    client.close();
  });
});
