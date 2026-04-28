/** SpaceRouter JavaScript SDK — route HTTP requests through residential IPs. */

export { SpaceRouter } from "./client.js";
export type { RequestOptions, SpaceRouterClientOptions } from "./client.js";

export { SpaceRouterAdmin } from "./admin.js";

export {
  SpaceRouterError,
  AuthenticationError,
  QuotaExceededError,
  RateLimitError,
  NoNodesAvailableError,
  UpstreamError,
  SettlementRejectedError,
} from "./errors.js";

export { SpaceRouterSPACE } from "./payment/spacecoin.js";
export type { SpaceRouterSPACEOptions } from "./payment/spacecoin.js";
export { ConsumerSettlementClient } from "./payment/consumerSettlement.js";
export type {
  ConsumerSettlementOptions,
  PendingFetchResult,
  SignatureSubmission,
  SignatureSubmitResult,
  SubmitOptions,
} from "./payment/consumerSettlement.js";

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

// ── v1.5 escrow / payment surface ──────────────────────────────────────
export { EscrowClient } from "./escrow.js";
export type {
  EscrowClientOptions,
  WithdrawalRequest,
} from "./escrow.js";
export { ESCROW_ABI, ERC20_ABI } from "./escrow.abi.js";

export { ClientPaymentWallet } from "./payment/clientWallet.js";
export type { AuthHeaders } from "./payment/clientWallet.js";

export {
  addressToBytes32,
  signReceipt,
  recoverReceiptSigner,
} from "./payment/eip712.js";
export type { EIP712Domain, Receipt } from "./payment/eip712.js";
