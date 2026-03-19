import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SpaceRouterAdmin } from "../src/index.js";
import type { ApiKey, ApiKeyInfo } from "../src/index.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(
  status: number,
  body?: unknown,
): ReturnType<typeof vi.fn> {
  const fn = vi.fn().mockResolvedValue(
    new Response(body != null ? JSON.stringify(body) : null, {
      status,
      headers: body != null ? { "content-type": "application/json" } : {},
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

// ---------------------------------------------------------------------------
// SpaceRouterAdmin
// ---------------------------------------------------------------------------

describe("SpaceRouterAdmin", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("createApiKey", () => {
    it("creates a key and returns ApiKey", async () => {
      const apiKey: ApiKey = {
        id: "key-uuid",
        name: "my-agent",
        api_key: "sr_live_abc123def456",
        rate_limit_rpm: 60,
      };
      const fetchSpy = mockFetch(201, apiKey);

      const admin = new SpaceRouterAdmin();
      const key = await admin.createApiKey("my-agent");

      expect(key.id).toBe("key-uuid");
      expect(key.api_key).toMatch(/^sr_live_/);
      expect(key.rate_limit_rpm).toBe(60);

      // Verify request
      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe("https://coordination.spacerouter.org/api-keys");
      expect(init.method).toBe("POST");
      const body = JSON.parse(init.body as string);
      expect(body.name).toBe("my-agent");
      expect(body.rate_limit_rpm).toBe(60);
      admin.close();
    });

    it("passes custom rate_limit_rpm", async () => {
      const fetchSpy = mockFetch(201, {
        id: "uuid",
        name: "fast",
        api_key: "sr_live_xyz",
        rate_limit_rpm: 200,
      });

      const admin = new SpaceRouterAdmin();
      const key = await admin.createApiKey("fast", { rateLimitRpm: 200 });
      expect(key.rate_limit_rpm).toBe(200);

      const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
      expect(body.rate_limit_rpm).toBe(200);
      admin.close();
    });

    it("throws on server error", async () => {
      mockFetch(500, { detail: "Internal error" });

      const admin = new SpaceRouterAdmin();
      await expect(admin.createApiKey("bad")).rejects.toThrow(
        "Failed to create API key: 500",
      );
      admin.close();
    });
  });

  describe("listApiKeys", () => {
    it("returns ApiKeyInfo[]", async () => {
      const keys: ApiKeyInfo[] = [
        {
          id: "1",
          name: "key-one",
          key_prefix: "sr_live_aaa",
          rate_limit_rpm: 60,
          is_active: true,
          created_at: "2025-01-01T00:00:00Z",
        },
        {
          id: "2",
          name: "key-two",
          key_prefix: "sr_live_bbb",
          rate_limit_rpm: 120,
          is_active: false,
          created_at: "2025-01-02T00:00:00Z",
        },
      ];
      const fetchSpy = mockFetch(200, keys);

      const admin = new SpaceRouterAdmin();
      const result = await admin.listApiKeys();

      expect(result).toHaveLength(2);
      expect(result[0].is_active).toBe(true);
      expect(result[1].is_active).toBe(false);
      expect(fetchSpy.mock.calls[0][1].method).toBe("GET");
      admin.close();
    });
  });

  describe("revokeApiKey", () => {
    it("sends DELETE and does not throw", async () => {
      const fetchSpy = mockFetch(204);

      const admin = new SpaceRouterAdmin();
      await admin.revokeApiKey("key-uuid");

      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe("https://coordination.spacerouter.org/api-keys/key-uuid");
      expect(init.method).toBe("DELETE");
      admin.close();
    });

    it("throws on error", async () => {
      mockFetch(500);

      const admin = new SpaceRouterAdmin();
      await expect(admin.revokeApiKey("bad")).rejects.toThrow(
        "Failed to revoke API key",
      );
      admin.close();
    });
  });

  // -- Node management ----------------------------------------------------

  describe("registerNode", () => {
    it("creates a node and returns Node", async () => {
      const node = {
        id: "node-uuid",
        endpoint_url: "http://192.168.1.100:9090",
        public_ip: "73.162.1.1",
        connectivity_type: "direct",
        node_type: "residential",
        status: "online",
        health_score: 1.0,
        region: "US",
        label: "my-node",
        ip_type: "residential",
        ip_region: "US",
        as_type: "isp",
        wallet_address: "0xabc",
        created_at: "2025-01-01T00:00:00Z",
        gateway_ca_cert: "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
      };
      const fetchSpy = mockFetch(201, node);

      const admin = new SpaceRouterAdmin();
      const result = await admin.registerNode({
        endpoint_url: "http://192.168.1.100:9090",
        wallet_address: "0xabc",
        label: "my-node",
      });

      expect(result.id).toBe("node-uuid");
      expect(result.status).toBe("online");
      const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
      expect(body.endpoint_url).toBe("http://192.168.1.100:9090");
      expect(body.wallet_address).toBe("0xabc");
      admin.close();
    });

    it("throws on server error", async () => {
      mockFetch(500);
      const admin = new SpaceRouterAdmin();
      await expect(
        admin.registerNode({ endpoint_url: "http://x", wallet_address: "0x" }),
      ).rejects.toThrow("Failed to register node");
      admin.close();
    });
  });

  describe("listNodes", () => {
    it("returns Node[]", async () => {
      const nodes = [
        {
          id: "n1", endpoint_url: "http://a", public_ip: "1.1.1.1",
          connectivity_type: "direct", node_type: "residential", status: "online",
          health_score: 0.9, region: "US", label: null, ip_type: "residential",
          ip_region: "US", as_type: "isp", wallet_address: "0x1",
          created_at: "2025-01-01T00:00:00Z",
          gateway_ca_cert: "CERT",
        },
      ];
      const fetchSpy = mockFetch(200, nodes);

      const admin = new SpaceRouterAdmin();
      const result = await admin.listNodes();
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe("n1");
      expect(fetchSpy.mock.calls[0][1].method).toBe("GET");
      admin.close();
    });
  });

  describe("updateNodeStatus", () => {
    it("sends PATCH", async () => {
      const fetchSpy = mockFetch(200, { ok: true });
      const admin = new SpaceRouterAdmin();
      await admin.updateNodeStatus("node-1", "draining");

      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe("https://coordination.spacerouter.org/nodes/node-1/status");
      expect(init.method).toBe("PATCH");
      const body = JSON.parse(init.body as string);
      expect(body.status).toBe("draining");
      admin.close();
    });
  });

  describe("deleteNode", () => {
    it("sends DELETE", async () => {
      const fetchSpy = mockFetch(204);
      const admin = new SpaceRouterAdmin();
      await admin.deleteNode("node-uuid");

      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe("https://coordination.spacerouter.org/nodes/node-uuid");
      expect(init.method).toBe("DELETE");
      admin.close();
    });
  });

  // -- Staking registration -----------------------------------------------

  describe("getRegisterChallenge", () => {
    it("returns challenge", async () => {
      const challenge = { nonce: "abc123", expires_in: 300 };
      const fetchSpy = mockFetch(200, challenge);

      const admin = new SpaceRouterAdmin();
      const result = await admin.getRegisterChallenge("0xwallet");
      expect(result.nonce).toBe("abc123");
      expect(result.expires_in).toBe(300);

      const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
      expect(body.address).toBe("0xwallet");
      admin.close();
    });
  });

  describe("verifyAndRegister", () => {
    it("returns register result", async () => {
      const regResult = {
        status: "registered",
        node_id: "node-new",
        address: "0xwallet",
        endpoint_url: "http://node:9090",
        gateway_ca_cert: "CERT",
      };
      mockFetch(200, regResult);

      const admin = new SpaceRouterAdmin();
      const result = await admin.verifyAndRegister({
        address: "0xwallet",
        endpoint_url: "http://node:9090",
        signed_nonce: "signed-abc",
      });
      expect(result.status).toBe("registered");
      expect(result.node_id).toBe("node-new");
      admin.close();
    });
  });

  // -- Billing ------------------------------------------------------------

  describe("createCheckout", () => {
    it("returns checkout URL", async () => {
      mockFetch(200, { checkout_url: "https://checkout.stripe.com/session" });

      const admin = new SpaceRouterAdmin();
      const result = await admin.createCheckout("user@example.com");
      expect(result.checkout_url).toContain("stripe.com");
      admin.close();
    });
  });

  describe("verifyEmail", () => {
    it("sends GET with token", async () => {
      const fetchSpy = mockFetch(200);
      const admin = new SpaceRouterAdmin();
      await admin.verifyEmail("token-123");

      const url = fetchSpy.mock.calls[0][0] as string;
      expect(url).toContain("/billing/verify?token=token-123");
      admin.close();
    });
  });

  describe("reissueApiKey", () => {
    it("returns new API key", async () => {
      mockFetch(200, { new_api_key: "sr_live_new_key" });

      const admin = new SpaceRouterAdmin();
      const result = await admin.reissueApiKey({
        email: "user@example.com",
        token: "tok",
      });
      expect(result.new_api_key).toBe("sr_live_new_key");
      admin.close();
    });
  });

  // -- Dashboard ----------------------------------------------------------

  describe("getTransfers", () => {
    it("returns paginated transfers", async () => {
      const page = {
        page: 1,
        total_pages: 5,
        total_bytes: 1024000,
        transfers: [
          {
            request_id: "req-1",
            bytes: 512,
            method: "GET",
            target_host: "example.com",
            created_at: "2025-01-01T00:00:00Z",
          },
        ],
      };
      const fetchSpy = mockFetch(200, page);

      const admin = new SpaceRouterAdmin();
      const result = await admin.getTransfers({
        wallet_address: "0xabc",
        page: 1,
        page_size: 10,
      });
      expect(result.total_pages).toBe(5);
      expect(result.transfers).toHaveLength(1);

      const url = fetchSpy.mock.calls[0][0] as string;
      expect(url).toContain("wallet_address=0xabc");
      expect(url).toContain("page=1");
      expect(url).toContain("page_size=10");
      admin.close();
    });
  });

  describe("custom base URL", () => {
    it("uses the provided base URL", async () => {
      const fetchSpy = mockFetch(200, []);

      const admin = new SpaceRouterAdmin("http://api.example.com:9000");
      await admin.listApiKeys();

      expect(fetchSpy.mock.calls[0][0]).toBe(
        "http://api.example.com:9000/api-keys",
      );
      admin.close();
    });

    it("strips trailing slash", async () => {
      const fetchSpy = mockFetch(200, []);

      const admin = new SpaceRouterAdmin("https://coordination.spacerouter.org/");
      await admin.listApiKeys();

      expect(fetchSpy.mock.calls[0][0]).toBe(
        "https://coordination.spacerouter.org/api-keys",
      );
      admin.close();
    });
  });
});
