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
