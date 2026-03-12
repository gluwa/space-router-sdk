/** SpaceRouter JavaScript SDK — route HTTP requests through residential IPs. */

export { SpaceRouter, fetchCaCert } from "./client.js";
export type { RequestOptions } from "./client.js";

export { SpaceRouterAdmin } from "./admin.js";

export {
  SpaceRouterError,
  AuthenticationError,
  RateLimitError,
  NoNodesAvailableError,
  UpstreamError,
} from "./errors.js";

export { ProxyResponse } from "./models.js";
export type {
  ApiKey,
  ApiKeyInfo,
  IpType,
  SpaceRouterOptions,
  SpaceRouterAdminOptions,
} from "./models.js";
