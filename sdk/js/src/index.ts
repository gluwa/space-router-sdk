/** SpaceRouter JavaScript SDK — route HTTP requests through residential IPs. */

export { SpaceRouter } from "./client.js";
export {
  EscrowClient,
  ESCROW_ABI,
  RECEIPT_EIP712_DOMAIN,
  receiptTypes,
} from "./escrow.js";
export type {
  Receipt as EscrowReceipt,
  SignedReceipt as EscrowSignedReceipt,
  PendingWithdrawal,
  SettlementResult,
  EscrowClientOptions,
} from "./escrow.js";
export type { RequestOptions } from "./client.js";

export { SpaceRouterAdmin } from "./admin.js";

export {
  SpaceRouterError,
  AuthenticationError,
  RateLimitError,
  NoNodesAvailableError,
  UpstreamError,
} from "./errors.js";

export {
  loadOrCreateIdentity,
  getAddress,
  signRequest,
  createVouchingSignature,
} from "./identity.js";

export { ProxyResponse, normalizeNode, normalizeRegisterResult } from "./models.js";
export type {
  ApiKey,
  ApiKeyInfo,
  BillingReissueResult,
  CheckoutSession,
  CreditLineStatus,
  IpType,
  Node,
  NodeConnectivityType,
  NodeStatus,
  RegisterChallenge,
  RegisterResult,
  SpaceRouterAdminOptions,
  SpaceRouterOptions,
  Transfer,
  TransferPage,
  VouchingSignature,
} from "./models.js";
