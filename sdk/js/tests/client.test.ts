import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import http from "node:http";
import type { AddressInfo } from "node:net";
import {
  SpaceRouter,
  ProxyResponse,
  AuthenticationError,
  RateLimitError,
  UpstreamError,
  NoNodesAvailableError,
} from "../src/index.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResponse(
  status: number,
  options?: {
    headers?: Record<string, string>;
    body?: unknown;
  },
): Response {
  const headers = new Headers(options?.headers);
  const body = options?.body ? JSON.stringify(options.body) : null;
  if (body) headers.set("content-type", "application/json");
  return new Response(body, { status, headers });
}

// ---------------------------------------------------------------------------
// ProxyResponse
// ---------------------------------------------------------------------------

describe("ProxyResponse", () => {
  it("exposes requestId from header", () => {
    const raw = makeResponse(200, {
      headers: { "x-spacerouter-request-id": "req-1" },
    });
    const resp = new ProxyResponse(raw);
    expect(resp.requestId).toBe("req-1");
  });

  it("returns undefined when headers missing", () => {
    const raw = makeResponse(200);
    const resp = new ProxyResponse(raw);
    expect(resp.requestId).toBeUndefined();
  });

  it("nodeId reads X-SpaceRouter-Node from inner response (HTTP target path)", () => {
    const raw = makeResponse(200, {
      headers: { "x-spacerouter-node": "node-http-1" },
    });
    const resp = new ProxyResponse(raw);
    expect(resp.nodeId).toBe("node-http-1");
  });

  it("nodeId prefers CONNECT-captured metadata when both are present", () => {
    // For HTTPS targets the inner Response can't carry SR headers (the
    // tunnel is encrypted end-to-end), so the CONNECT capture is the
    // only source. When both happen to be present (HTTP target served
    // by a fallback path that also runs CONNECT capture), capture wins
    // — it reflects the gateway's view at tunnel-establishment time.
    const raw = makeResponse(200, {
      headers: { "x-spacerouter-node": "from-inner" },
    });
    const resp = new ProxyResponse(raw, { nodeId: "from-connect" });
    expect(resp.nodeId).toBe("from-connect");
  });

  it("nodeId is undefined when neither metadata nor inner header is set", () => {
    const resp = new ProxyResponse(makeResponse(200));
    expect(resp.nodeId).toBeUndefined();
  });

  it("requestId falls back to inner header when metadata absent", () => {
    const raw = makeResponse(200, {
      headers: { "x-spacerouter-request-id": "req-fallback" },
    });
    const resp = new ProxyResponse(raw);
    expect(resp.requestId).toBe("req-fallback");
  });

  it("routingTag exposes home/fallback distinction", () => {
    const raw = makeResponse(200, {
      headers: { "x-spacerouter-routing": "home" },
    });
    const resp = new ProxyResponse(raw);
    expect(resp.routingTag).toBe("home");
  });

  it("delegates status", () => {
    const raw = makeResponse(201);
    const resp = new ProxyResponse(raw);
    expect(resp.status).toBe(201);
  });

  it("delegates ok", () => {
    expect(new ProxyResponse(makeResponse(200)).ok).toBe(true);
    expect(new ProxyResponse(makeResponse(404)).ok).toBe(false);
  });

  it("delegates json()", async () => {
    const raw = makeResponse(200, { body: { hello: "world" } });
    const resp = new ProxyResponse(raw);
    expect(await resp.json()).toEqual({ hello: "world" });
  });

  it("delegates text()", async () => {
    const raw = new Response("hello", { status: 200 });
    const resp = new ProxyResponse(raw);
    expect(await resp.text()).toBe("hello");
  });

  it("exposes raw response", () => {
    const raw = makeResponse(200);
    const resp = new ProxyResponse(raw);
    expect(resp.raw).toBe(raw);
  });

  it("has toString()", () => {
    const resp = new ProxyResponse(makeResponse(200));
    expect(resp.toString()).toContain("200");
  });
});

// ---------------------------------------------------------------------------
// checkProxyErrors (tested through SpaceRouter)
// ---------------------------------------------------------------------------

describe("proxy error checking", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("407 throws AuthenticationError", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(407, {
        headers: { "x-spacerouter-request-id": "req-1" },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    await expect(client.get("http://example.com")).rejects.toThrow(
      AuthenticationError,
    );

    try {
      await client.get("http://example.com");
    } catch (e) {
      expect(e).toBeInstanceOf(AuthenticationError);
      expect((e as AuthenticationError).statusCode).toBe(407);
      expect((e as AuthenticationError).requestId).toBe("req-1");
    }
    client.close();
  });

  // --- CONNECT-time error mapping (mocked) -----------------------------------
  //
  // These tests cover the cause-chain walker without spinning up a real
  // server. The realistic 3-deep chain (matches what production undici emits
  // and what we validated against the test gateway) is the primary case;
  // the 1-deep chain is a defensive test in case future undici versions stop
  // wrapping in DOMException.
  //
  // The live-undici tests further down validate the real chain shape so a
  // future regression is caught automatically.

  function build3LevelChain(innerMessage: string): TypeError {
    // Real undici production chain (rc.9 confirmed):
    //   TypeError("fetch failed")
    //     .cause = DOMException("Request was cancelled.")
    //       .cause = RequestAbortedError("Proxy response (4xx/5xx) ...")
    const inner = new Error(innerMessage);
    inner.name = "RequestAbortedError";
    const middle = new Error("Request was cancelled.") as Error & {
      cause?: unknown;
    };
    middle.name = "DOMException";
    middle.cause = inner;
    return new TypeError("fetch failed", { cause: middle });
  }

  it("407 during HTTPS CONNECT (3-deep cause chain) throws AuthenticationError", async () => {
    // Reproduces the real production chain that previously slipped past
    // rc.6's L1-only check.
    fetchSpy.mockRejectedValue(
      build3LevelChain("Proxy response (407) !== 200 when HTTP Tunneling"),
    );

    const client = new SpaceRouter("sr_live_bad_key");
    await expect(client.get("https://example.com")).rejects.toThrow(
      AuthenticationError,
    );

    try {
      await client.get("https://example.com");
    } catch (e) {
      expect(e).toBeInstanceOf(AuthenticationError);
      expect((e as AuthenticationError).statusCode).toBe(407);
    }
    client.close();
  });

  it("503 during HTTPS CONNECT (3-deep cause chain) throws NoNodesAvailableError", async () => {
    // Reproduces the real production chain that previously slipped past
    // rc.8's L1-only check.
    fetchSpy.mockRejectedValue(
      build3LevelChain("Proxy response (503) !== 200 when HTTP Tunneling"),
    );

    const client = new SpaceRouter("sr_live_xxx");
    await expect(client.get("https://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );

    try {
      await client.get("https://example.com");
    } catch (e) {
      expect(e).toBeInstanceOf(NoNodesAvailableError);
      expect((e as NoNodesAvailableError).statusCode).toBe(503);
    }
    client.close();
  });

  it("407 during HTTPS CONNECT (1-deep cause, defensive) still maps", async () => {
    // Defensive — if undici drops the DOMException wrapper in a future
    // release, the walker should still match at L1.
    const cause = new Error("proxy authentication required");
    fetchSpy.mockRejectedValue(new TypeError("fetch failed", { cause }));

    const client = new SpaceRouter("sr_live_bad_key");
    await expect(client.get("https://example.com")).rejects.toThrow(
      AuthenticationError,
    );
    client.close();
  });

  it("503 during HTTPS CONNECT (1-deep cause, defensive) still maps", async () => {
    const cause = new Error("Proxy response (503) !== 200 when HTTP Tunneling");
    fetchSpy.mockRejectedValue(new TypeError("fetch failed", { cause }));

    const client = new SpaceRouter("sr_live_xxx");
    await expect(client.get("https://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );
    client.close();
  });

  it("429 throws RateLimitError with retryAfter", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(429, {
        headers: {
          "retry-after": "42",
          "x-spacerouter-request-id": "req-2",
        },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    try {
      await client.get("http://example.com");
    } catch (e) {
      expect(e).toBeInstanceOf(RateLimitError);
      expect((e as RateLimitError).retryAfter).toBe(42);
      expect((e as RateLimitError).requestId).toBe("req-2");
    }
    client.close();
  });

  it("429 defaults retryAfter to 60", async () => {
    fetchSpy.mockResolvedValue(makeResponse(429));

    const client = new SpaceRouter("sr_live_test");
    try {
      await client.get("http://example.com");
    } catch (e) {
      expect((e as RateLimitError).retryAfter).toBe(60);
    }
    client.close();
  });

  it("502 throws UpstreamError", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(502, {
        headers: {
          "x-spacerouter-request-id": "req-3",
        },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    try {
      await client.get("http://example.com");
    } catch (e) {
      expect(e).toBeInstanceOf(UpstreamError);
      expect((e as UpstreamError).requestId).toBe("req-3");
    }
    client.close();
  });

  it("503 with no_nodes_available throws NoNodesAvailableError with body message", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(503, {
        body: { error: "no_nodes_available", message: "specific msg" },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    await expect(client.get("http://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );
    await expect(client.get("http://example.com")).rejects.toThrow(
      /specific msg/,
    );
    client.close();
  });

  it("503 with empty body maps to NoNodesAvailableError (generic message)", async () => {
    fetchSpy.mockResolvedValue(makeResponse(503));

    const client = new SpaceRouter("sr_live_test");
    await expect(client.get("http://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );
    await expect(client.get("http://example.com")).rejects.toThrow(
      /No residential nodes currently available/,
    );
    client.close();
  });

  it("503 with other body shape still maps to NoNodesAvailableError", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(503, { body: { detail: "upstream timeout" } }),
    );

    const client = new SpaceRouter("sr_live_test");
    await expect(client.get("http://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );
    client.close();
  });

  it("200 passes through", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(200, {
        headers: {
          "x-spacerouter-request-id": "req-ok",
        },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    const resp = await client.get("http://example.com");
    expect(resp.status).toBe(200);
    expect(resp.requestId).toBe("req-ok");
    client.close();
  });

  it("404 from target passes through", async () => {
    fetchSpy.mockResolvedValue(makeResponse(404));

    const client = new SpaceRouter("sr_live_test");
    const resp = await client.get("http://example.com");
    expect(resp.status).toBe(404);
    client.close();
  });
});

// ---------------------------------------------------------------------------
// SpaceRouter construction
// ---------------------------------------------------------------------------

describe("SpaceRouter", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn().mockResolvedValue(makeResponse(200));
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("defaults to HTTP protocol", () => {
    const client = new SpaceRouter("sr_live_test");
    expect(client.toString()).toContain("protocol=http");
    client.close();
  });

  it("accepts socks5 protocol", () => {
    const client = new SpaceRouter("sr_live_test", {
      protocol: "socks5",
      gatewayUrl: "socks5://gw:1080",

    });
    expect(client.toString()).toContain("protocol=socks5");
    client.close();
  });

  it("toString includes gateway url", () => {
    const client = new SpaceRouter("sr_live_test", {
      gatewayUrl: "http://gw:8080",

    });
    expect(client.toString()).toContain("http://gw:8080");
    client.close();
  });

  it("withRouting returns new client", () => {
    const client = new SpaceRouter("sr_live_test");
    const routed = client.withRouting({ region: "KR" });
    expect(routed).not.toBe(client);
    expect(routed.toString()).toContain("protocol=http");
    client.close();
    routed.close();
  });

  it("withRouting accepts ipType", () => {
    const client = new SpaceRouter("sr_live_test");
    const routed = client.withRouting({ ipType: "residential" });
    expect(routed).not.toBe(client);
    client.close();
    routed.close();
  });

  // --- routing header tests ---
  // Region/ipType MUST land on the proxy CONNECT (in the ProxyAgent's
  // headers dict) — NOT on the inner request — because the gateway can't
  // read inside the TLS-tunnelled inner request. We assert by capturing the
  // dispatcher passed to fetch and reading ProxyAgent's internal Symbol-keyed
  // headers slot (set by the constructor in src/client.ts:buildAgent).
  function getConnectHeaders(dispatcher: unknown): Record<string, string> {
    // undici stores ProxyAgent's connect-time headers under Symbol("proxy headers")
    const sym = Object.getOwnPropertySymbols(dispatcher as object).find(
      (s) => s.description === "proxy headers",
    );
    if (!sym) return {};
    const v = (dispatcher as Record<symbol, unknown>)[sym];
    if (v && typeof v === "object" && !Array.isArray(v)) return v as Record<string, string>;
    return {};
  }

  it("injects IP-type header on proxy CONNECT", async () => {
    let captured: any;
    fetchSpy.mockImplementation(async (_u: any, init: any) => {
      captured = init?.dispatcher;
      return makeResponse(200);
    });
    const client = new SpaceRouter("sr_live_test", { ipType: "residential" });
    await client.get("http://example.com");
    const h = getConnectHeaders(captured);
    expect(h["X-SpaceRouter-IP-Type"]).toBe("residential");
    client.close();
  });

  it("does not inject IP-type header when unset", async () => {
    let captured: any;
    fetchSpy.mockImplementation(async (_u: any, init: any) => {
      captured = init?.dispatcher;
      return makeResponse(200);
    });
    const client = new SpaceRouter("sr_live_test");
    await client.get("http://example.com");
    const h = getConnectHeaders(captured);
    expect(h["X-SpaceRouter-IP-Type"]).toBeUndefined();
    client.close();
  });

  it("injects both region and IP-type headers on proxy CONNECT", async () => {
    let captured: any;
    fetchSpy.mockImplementation(async (_u: any, init: any) => {
      captured = init?.dispatcher;
      return makeResponse(200);
    });
    const client = new SpaceRouter("sr_live_test", {
      region: "US",
      ipType: "mobile",
    });
    await client.get("http://example.com");
    const h = getConnectHeaders(captured);
    expect(h["X-SpaceRouter-Region"]).toBe("US");
    expect(h["X-SpaceRouter-IP-Type"]).toBe("mobile");
    client.close();
  });

  it("rejects invalid region", () => {
    expect(() => new SpaceRouter("sr_live_test", { region: "Seoul, KR" })).toThrow(
      "2-letter country code",
    );
    expect(() => new SpaceRouter("sr_live_test", { region: "USA" })).toThrow(
      "2-letter country code",
    );
    expect(() => new SpaceRouter("sr_live_test", { region: "us" })).toThrow(
      "2-letter country code",
    );
  });

  it("injects routing headers on proxy CONNECT", async () => {
    let captured: any;
    fetchSpy.mockImplementation(async (_u: any, init: any) => {
      captured = init?.dispatcher;
      return makeResponse(200);
    });
    const client = new SpaceRouter("sr_live_test", { region: "US" });
    await client.get("http://example.com");
    const h = getConnectHeaders(captured);
    expect(h["X-SpaceRouter-Region"]).toBe("US");
    client.close();
  });

  it("does not inject routing headers when unset", async () => {
    let captured: any;
    fetchSpy.mockImplementation(async (_u: any, init: any) => {
      captured = init?.dispatcher;
      return makeResponse(200);
    });
    const client = new SpaceRouter("sr_live_test");
    await client.get("http://example.com");
    const h = getConnectHeaders(captured);
    expect(h["X-SpaceRouter-Region"]).toBeUndefined();
    client.close();
  });

  it("post passes body", async () => {
    const client = new SpaceRouter("sr_live_test");
    const body = JSON.stringify({ key: "value" });
    await client.post("http://example.com/data", { body });

    expect(fetchSpy.mock.calls[0][1].method).toBe("POST");
    expect(fetchSpy.mock.calls[0][1].body).toBe(body);
    client.close();
  });

  it("passes custom headers", async () => {
    const client = new SpaceRouter("sr_live_test");
    await client.get("http://example.com", {
      headers: { "X-Custom": "value" },
    });

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-Custom"]).toBe("value");
    client.close();
  });
});

// ---------------------------------------------------------------------------
// CONNECT-time error mapping — LIVE undici against a local CONNECT server
// ---------------------------------------------------------------------------
//
// These tests do NOT mock fetch. They spin up a tiny local HTTP proxy that
// answers `CONNECT` with a real non-200 status, so undici produces the real
// cause chain. This is the only kind of test that would have caught the
// 5-cycle bug — a mocked TypeError with a hand-built single-level cause
// (as the previous tests had it) doesn't reproduce the production chain
// shape and silently lets the L1-only check pass.
//
// If any future undici release changes the cause-chain depth or wrapper
// shape, these tests will fail loudly here without us having to re-discover
// the bug in production.

describe("CONNECT-time error mapping (live undici)", () => {
  beforeEach(() => {
    // Earlier `describe` blocks stub `globalThis.fetch` via vi.stubGlobal.
    // `vi.restoreAllMocks()` does NOT undo that — only `vi.unstubAllGlobals`
    // does. Without this, the live tests would call the leftover spy and
    // never exercise undici. Belt and braces.
    vi.unstubAllGlobals();
  });

  function startProxy(status: number, reason: string): Promise<{
    port: number;
    close: () => Promise<void>;
  }> {
    return new Promise((resolve) => {
      const server = http.createServer();
      server.on("connect", (_req, socket) => {
        socket.write(`HTTP/1.1 ${status} ${reason}\r\n\r\n`);
        socket.end();
      });
      // Suppress noisy 'clientError' from undici tearing down the socket.
      server.on("clientError", () => {});
      server.listen(0, "127.0.0.1", () => {
        const port = (server.address() as AddressInfo).port;
        resolve({
          port,
          close: () =>
            new Promise<void>((r) => server.close(() => r())),
        });
      });
    });
  }

  it("407 CONNECT → AuthenticationError (real undici cause chain)", async () => {
    const proxy = await startProxy(407, "Proxy Authentication Required");
    try {
      const client = new SpaceRouter("sr_live_bad_key", {
        gatewayUrl: `http://127.0.0.1:${proxy.port}`,
      });
      let caught: unknown;
      try {
        await client.get("https://httpbin.org/ip");
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(AuthenticationError);
      expect((caught as AuthenticationError).statusCode).toBe(407);
      client.close();
    } finally {
      await proxy.close();
    }
  });

  it("503 CONNECT → NoNodesAvailableError (real undici cause chain)", async () => {
    const proxy = await startProxy(503, "Service Unavailable");
    try {
      const client = new SpaceRouter("sr_live_xxx", {
        gatewayUrl: `http://127.0.0.1:${proxy.port}`,
      });
      let caught: unknown;
      try {
        await client.get("https://httpbin.org/ip");
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(NoNodesAvailableError);
      expect((caught as NoNodesAvailableError).statusCode).toBe(503);
      client.close();
    } finally {
      await proxy.close();
    }
  });
});
