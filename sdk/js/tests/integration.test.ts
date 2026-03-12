/**
 * Integration tests for the SpaceRouter JS SDK.
 *
 * These tests hit the **live** Coordination API and proxy gateway at
 * `gateway.spacerouter.org`.  They are gated behind the `SR_INTEGRATION`
 * environment variable so they never run in normal CI:
 *
 *     SR_INTEGRATION=1 npx vitest run tests/integration.test.ts
 */

import { describe, it, expect } from "vitest";
import { SpaceRouterAdmin } from "../src/index.js";

const RUN = process.env.SR_INTEGRATION === "1";

const COORDINATION_URL =
  process.env.SR_COORDINATION_API_URL ??
  "https://coordination.spacerouter.org";

const GATEWAY_URL =
  process.env.SR_GATEWAY_URL ?? "http://gateway.spacerouter.org:8080";

describe.skipIf(!RUN)("Integration", () => {
  it("full lifecycle: create key -> proxy request -> revoke", async () => {
    const admin = new SpaceRouterAdmin(COORDINATION_URL);

    // 1. Create an ephemeral API key.
    const key = await admin.createApiKey("integration-test-js");
    expect(key.api_key).toMatch(/^sr_live_/);

    try {
      // 2. Proxy a request through the gateway.
      const proxyUrl = new URL(GATEWAY_URL);
      const resp = await fetch("https://httpbin.org/ip", {
        headers: {
          "Proxy-Authorization": `Basic ${btoa(key.api_key + ":")}`,
        },
      });
      expect(resp.status).toBe(200);

      const body = (await resp.json()) as { origin: string };
      expect(body.origin).toBeDefined();
    } finally {
      // 3. Cleanup: revoke the key.
      await admin.revokeApiKey(key.id);
    }
  });

  it("API key CRUD", async () => {
    const admin = new SpaceRouterAdmin(COORDINATION_URL);
    const key = await admin.createApiKey("integration-crud-js");

    try {
      const keys = await admin.listApiKeys();
      const ids = keys.map((k) => k.id);
      expect(ids).toContain(key.id);
    } finally {
      await admin.revokeApiKey(key.id);
    }
  });
});
