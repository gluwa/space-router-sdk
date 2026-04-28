/**
 * Integration tests for the SpaceRouter JS SDK.
 *
 * These tests hit the **live** Coordination API and proxy gateway at
 * `gateway.spacerouter.org`.  They require the `SR_API_KEY` environment
 * variable to be set to a billing-provisioned key:
 *
 *     SR_API_KEY=sr_live_xxx npx vitest run tests/integration.test.ts
 */

import { describe, it, expect } from "vitest";
import { SpaceRouterAdmin, SpaceRouter } from "../src/index.js";

const COORDINATION_URL =
  process.env.SR_COORDINATION_API_URL ??
  "https://coordination.spacerouter.org";

const GATEWAY_URL =
  process.env.SR_GATEWAY_URL ?? "https://gateway.spacerouter.org";

/** A billing-provisioned API key for proxy tests. */
const API_KEY = process.env.SR_API_KEY;

describe.skipIf(!API_KEY)("Integration", () => {
  it("proxy request with billing-provisioned key", { timeout: 30_000 }, async () => {
    const client = new SpaceRouter(API_KEY!, {
      gatewayUrl: GATEWAY_URL,
    });
    try {
      const resp = await client.get("https://httpbin.org/ip");
      expect(resp.status).toBe(200);

      const body = (await resp.json()) as { origin: string };
      expect(body.origin).toBeDefined();
    } finally {
      client.close();
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

  it("node list", async () => {
    const admin = new SpaceRouterAdmin(COORDINATION_URL);
    const nodes = await admin.listNodes();
    expect(Array.isArray(nodes)).toBe(true);
  });
});
