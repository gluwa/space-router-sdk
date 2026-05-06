/**
 * `verify` option — TLS cert verification toggle for the gateway connection.
 *
 * QA on the test environment hit `SELF_SIGNED_CERT_IN_CHAIN` when calling
 * `withRouting({region:"US"})` against the staging gateway (self-signed
 * cert chain). The Python CLI got an `--insecure` flag in rc.6 but the JS
 * SDK constructor had no equivalent option, so JS consumers couldn't talk
 * to the test gateway at all. This pins the wiring: `verify:false` must
 * propagate to the underlying undici `CapturingProxyAgent` as
 * `proxyTls: { rejectUnauthorized: false }` (and the symmetric
 * `requestTls`) without actually opening a network connection.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// vi.mock hoists, so the captured-args store has to be lazy-initialised
// inside the factory to avoid the "cannot access before initialisation"
// trap. We expose it on globalThis so the test body can read it.
vi.mock("../src/proxyAgent.js", () => {
  const captured: Array<Record<string, unknown>> = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).__capturedProxyAgentOpts = captured;

  class CapturingProxyAgentMock {
    public lastNodeId?: string;
    public lastRequestId?: string;
    public lastRoutingTag?: string;
    constructor(opts: Record<string, unknown>) {
      captured.push(opts);
    }
    capturedMetadata() {
      return {
        nodeId: this.lastNodeId,
        requestId: this.lastRequestId,
        routingTag: this.lastRoutingTag,
      };
    }
    close() {
      /* noop */
    }
  }

  return { CapturingProxyAgent: CapturingProxyAgentMock };
});

// Imported AFTER vi.mock so the mock is in place.
import { SpaceRouter } from "../src/client.js";

function getCapturedOpts(): Array<Record<string, unknown>> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (globalThis as any).__capturedProxyAgentOpts as Array<
    Record<string, unknown>
  >;
}

describe("SpaceRouter `verify` option (TLS cert verification)", () => {
  beforeEach(() => {
    getCapturedOpts().length = 0;
  });

  it("passes rejectUnauthorized:false when verify:false (HTTPS gateway)", () => {
    new SpaceRouter("sr_test_xxx", {
      gatewayUrl: "https://gateway.test.spacerouter.org",
      verify: false,
    });

    const opts = getCapturedOpts();
    expect(opts).toHaveLength(1);
    // Both the proxy hop (gateway TLS) and the inner CONNECT-tunnelled
    // request must skip verification — disabling only proxyTls left the
    // inner request strict and re-triggered the same failure mode in QA.
    expect(opts[0].proxyTls).toEqual({ rejectUnauthorized: false });
    expect(opts[0].requestTls).toEqual({ rejectUnauthorized: false });
  });

  it("does NOT set proxyTls/requestTls when verify is omitted (default true)", () => {
    new SpaceRouter("sr_test_xxx", {
      gatewayUrl: "https://gateway.spacerouter.org",
    });

    const opts = getCapturedOpts();
    expect(opts).toHaveLength(1);
    // Default behaviour is unchanged — undici uses its standard TLS
    // verification path, so we explicitly DO NOT pass these keys.
    expect(opts[0].proxyTls).toBeUndefined();
    expect(opts[0].requestTls).toBeUndefined();
  });

  it("does NOT set proxyTls/requestTls when verify:true is explicit", () => {
    new SpaceRouter("sr_test_xxx", {
      gatewayUrl: "https://gateway.spacerouter.org",
      verify: true,
    });

    const opts = getCapturedOpts();
    expect(opts).toHaveLength(1);
    expect(opts[0].proxyTls).toBeUndefined();
    expect(opts[0].requestTls).toBeUndefined();
  });

  it("withRouting carries verify:false through to the new client", () => {
    const client = new SpaceRouter("sr_test_xxx", {
      gatewayUrl: "https://gateway.test.spacerouter.org",
      verify: false,
    });
    // Clear the constructor capture from the parent client, leaving
    // only the agent built by withRouting.
    getCapturedOpts().length = 0;

    client.withRouting({ region: "US" });

    const opts = getCapturedOpts();
    expect(opts).toHaveLength(1);
    expect(opts[0].proxyTls).toEqual({ rejectUnauthorized: false });
    expect(opts[0].requestTls).toEqual({ rejectUnauthorized: false });
  });

  it("preserves existing CONNECT headers (auth/region) alongside verify:false", () => {
    new SpaceRouter("sr_test_xxx", {
      gatewayUrl: "https://gateway.test.spacerouter.org",
      region: "US",
      verify: false,
    });

    const opts = getCapturedOpts();
    const headers = opts[0].headers as Record<string, string>;
    // verify wiring must not interfere with the auth + routing headers
    // the rest of the SDK depends on for the proxy CONNECT.
    expect(headers["Proxy-Authorization"]).toMatch(/^Basic /);
    expect(headers["X-SpaceRouter-Region"]).toBe("US");
  });
});
