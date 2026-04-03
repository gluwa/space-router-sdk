import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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

  it("503 with no_nodes_available throws NoNodesAvailableError", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(503, {
        body: { error: "no_nodes_available", message: "..." },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    await expect(client.get("http://example.com")).rejects.toThrow(
      NoNodesAvailableError,
    );
    client.close();
  });

  it("503 with other error passes through", async () => {
    fetchSpy.mockResolvedValue(
      makeResponse(503, {
        body: { error: "something_else", message: "..." },
      }),
    );

    const client = new SpaceRouter("sr_live_test");
    const resp = await client.get("http://example.com");
    expect(resp.status).toBe(503);
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

  it("injects IP-type header", async () => {
    const client = new SpaceRouter("sr_live_test", {
      ipType: "residential",

    });

    await client.get("http://example.com");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const callArgs = fetchSpy.mock.calls[0];
    const headers = callArgs[1].headers;
    expect(headers["X-SpaceRouter-IP-Type"]).toBe("residential");
    client.close();
  });

  it("does not inject IP-type header when unset", async () => {
    const client = new SpaceRouter("sr_live_test");
    await client.get("http://example.com");

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-SpaceRouter-IP-Type"]).toBeUndefined();
    client.close();
  });

  it("injects both region and IP-type headers", async () => {
    const client = new SpaceRouter("sr_live_test", {
      region: "US",
      ipType: "mobile",

    });

    await client.get("http://example.com");

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-SpaceRouter-Region"]).toBe("US");
    expect(headers["X-SpaceRouter-IP-Type"]).toBe("mobile");
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

  it("injects routing headers", async () => {
    const client = new SpaceRouter("sr_live_test", {
      region: "US",

    });

    await client.get("http://example.com");

    expect(fetchSpy).toHaveBeenCalledOnce();
    const callArgs = fetchSpy.mock.calls[0];
    const headers = callArgs[1].headers;
    expect(headers["X-SpaceRouter-Region"]).toBe("US");
    client.close();
  });

  it("does not inject routing headers when unset", async () => {
    const client = new SpaceRouter("sr_live_test");
    await client.get("http://example.com");

    const headers = fetchSpy.mock.calls[0][1].headers;
    expect(headers["X-SpaceRouter-Region"]).toBeUndefined();
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
// listRegions
// ---------------------------------------------------------------------------

describe("listRegions", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;
  beforeEach(() => { fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("calls GET /regions on coordination API", async () => {
    fetchSpy.mockResolvedValue(makeResponse(200, {
      body: { regions: [{ region: "US", ip_types: ["residential"] }], brightdata_available: true },
    }));
    const client = new SpaceRouter("sr_live_test", { coordinationApiUrl: "https://coord.test" });
    const result = await client.listRegions();
    expect(result.regions).toHaveLength(1);
    expect(result.regions[0].region).toBe("US");
    expect(result.brightdata_available).toBe(true);
    expect(fetchSpy.mock.calls[0][0]).toBe("https://coord.test/regions");
    client.close();
  });

  it("passes ip_type query param", async () => {
    fetchSpy.mockResolvedValue(makeResponse(200, {
      body: { regions: [], brightdata_available: false },
    }));
    const client = new SpaceRouter("sr_live_test", { coordinationApiUrl: "https://coord.test" });
    await client.listRegions("residential");
    expect(fetchSpy.mock.calls[0][0]).toContain("ip_type=residential");
    client.close();
  });

  it("throws on error response", async () => {
    fetchSpy.mockResolvedValue(new Response("err", { status: 500 }));
    const client = new SpaceRouter("sr_live_test");
    await expect(client.listRegions()).rejects.toThrow("Failed to list regions");
    client.close();
  });
});

