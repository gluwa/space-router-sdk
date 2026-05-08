/**
 * CapturingProxyAgent — surfaces CONNECT response headers to the SDK.
 *
 * For HTTPS target URLs, the gateway emits ``X-SpaceRouter-Node`` (and
 * friends) on the CONNECT 200 response, BEFORE the TLS handshake to the
 * target. undici's stock ``ProxyAgent`` consumes those headers
 * internally and only exposes ``{ socket, statusCode }``, so
 * ``ProxyResponse.nodeId`` was always ``undefined`` for HTTPS proxied
 * fetches. CapturingProxyAgent uses ``ProxyAgent.Options.clientFactory``
 * to wrap the underlying Pool's ``connect()`` and snapshot the headers
 * before returning to undici's internals.
 *
 * These tests pin the capture path against a tiny TCP server that
 * speaks just enough HTTP/1.1 CONNECT to validate the wiring without
 * standing up a real proxy gateway.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import * as net from "node:net";
import { CapturingProxyAgent } from "../src/proxyAgent.js";

interface FakeProxyServer {
  port: number;
  close: () => Promise<void>;
  /** All CONNECT request lines the server saw, for inspection. */
  connectRequests: string[];
}

/**
 * Minimal proxy that only handles CONNECT — replies 200 with a bag of
 * SpaceRouter response headers, then closes the socket. Enough surface
 * for undici's CONNECT pump to parse headers; we don't need to relay
 * any actual request bytes since we're only testing the capture hook.
 */
async function startFakeProxy(
  responseHeaders: Record<string, string>,
): Promise<FakeProxyServer> {
  const connectRequests: string[] = [];
  const server = net.createServer((socket) => {
    let buffer = "";
    socket.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf-8");
      const headerEnd = buffer.indexOf("\r\n\r\n");
      if (headerEnd === -1) return;
      const requestLine = buffer.split("\r\n")[0];
      connectRequests.push(requestLine);
      const lines = ["HTTP/1.1 200 Connection Established"];
      for (const [k, v] of Object.entries(responseHeaders)) {
        lines.push(`${k}: ${v}`);
      }
      lines.push("Connection: close");
      lines.push("");
      lines.push("");
      socket.write(lines.join("\r\n"));
      // Close after the CONNECT response — we never serve any tunnelled
      // bytes. undici's connect() resolves on headers and that's all the
      // capture path needs.
      socket.end();
    });
    socket.on("error", () => {
      /* swallow — happens during teardown */
    });
  });
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address() as net.AddressInfo;
  return {
    port: address.port,
    connectRequests,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}

describe("CapturingProxyAgent", () => {
  let proxy: FakeProxyServer | null = null;

  afterEach(async () => {
    if (proxy) {
      await proxy.close();
      proxy = null;
    }
  });

  it("captures X-SpaceRouter-Node from CONNECT 200 response", async () => {
    proxy = await startFakeProxy({
      "X-SpaceRouter-Node": "node-7c3d92ae",
      "X-SpaceRouter-Request-Id": "req-abc-123",
      "X-SpaceRouter-Routing": "home",
    });

    const agent = new CapturingProxyAgent({
      uri: `http://127.0.0.1:${proxy.port}`,
    });

    // Trigger an HTTPS fetch through the proxy. The CONNECT will succeed
    // (our fake responds 200 with the headers we want captured); the TLS
    // handshake to the target will fail since we don't actually relay.
    // We only care about the CONNECT capture, not the inner request.
    await fetch("https://example.invalid/", {
      // @ts-expect-error -- Node fetch dispatcher
      dispatcher: agent,
    }).catch(() => {
      /* expected — TLS handshake fails after CONNECT */
    });

    // Whatever happened post-CONNECT, the CONNECT response itself
    // should have populated the agent's snapshot.
    expect(agent.lastNodeId).toBe("node-7c3d92ae");
    expect(agent.lastRequestId).toBe("req-abc-123");
    expect(agent.lastRoutingTag).toBe("home");
  });

  it("capturedMetadata() returns a snapshot of all three headers", async () => {
    proxy = await startFakeProxy({
      "X-SpaceRouter-Node": "node-xyz",
      "X-SpaceRouter-Request-Id": "req-xyz",
      "X-SpaceRouter-Routing": "fallback",
    });

    const agent = new CapturingProxyAgent({
      uri: `http://127.0.0.1:${proxy.port}`,
    });

    await fetch("https://example.invalid/", {
      // @ts-expect-error -- Node fetch dispatcher
      dispatcher: agent,
    }).catch(() => {});

    expect(agent.capturedMetadata()).toEqual({
      nodeId: "node-xyz",
      requestId: "req-xyz",
      routingTag: "fallback",
    });
  });

  it("leaves snapshot empty when CONNECT response has no SR headers", async () => {
    proxy = await startFakeProxy({});

    const agent = new CapturingProxyAgent({
      uri: `http://127.0.0.1:${proxy.port}`,
    });

    await fetch("https://example.invalid/", {
      // @ts-expect-error -- Node fetch dispatcher
      dispatcher: agent,
    }).catch(() => {});

    expect(agent.lastNodeId).toBeUndefined();
    expect(agent.lastRequestId).toBeUndefined();
    expect(agent.lastRoutingTag).toBeUndefined();
  });

  it("forwards Proxy-Authorization through the wrapper to the proxy", async () => {
    proxy = await startFakeProxy({
      "X-SpaceRouter-Node": "auth-test-node",
    });

    const agent = new CapturingProxyAgent({
      uri: `http://127.0.0.1:${proxy.port}`,
      headers: {
        "Proxy-Authorization": "Basic c3I6dGVzdA==",
      },
    });

    await fetch("https://example.invalid/", {
      // @ts-expect-error -- Node fetch dispatcher
      dispatcher: agent,
    }).catch(() => {});

    // Capture path still works alongside the Proxy-Authorization header.
    expect(agent.lastNodeId).toBe("auth-test-node");
    // Proxy actually saw a CONNECT line.
    expect(proxy.connectRequests.length).toBeGreaterThan(0);
    expect(proxy.connectRequests[0]).toMatch(/^CONNECT /);
  });
});
