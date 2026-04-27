/**
 * Consumer-side Leg 1 settlement broker client.
 *
 * Implements the out-of-band Leg 1 receipt-exchange protocol described in
 * `internal-docs/v1.5-consumer-protocol.md` §3-4 and §9 (negative paths):
 *
 *   GET  {gateway_mgmt}/leg1/pending  ?address&ts&sig[&limit]
 *   POST {gateway_mgmt}/leg1/sign     {address, ts, sig, signatures: [...]}
 *
 * EIP-191 auth messages (§4):
 *   space-router:leg1-list-pending:<addr-lowercase>:<ts>
 *   space-router:leg1-sign:<addr-lowercase>:<ts>
 *
 * Strict-mode rejection raises `SettlementRejectedError`; non-strict
 * surfaces the full reasons list so callers can decide.
 */

import { type ClientPaymentWallet } from "./clientWallet.js";
import { type EIP712Domain, type Receipt } from "./eip712.js";
import { SettlementRejectedError } from "../errors.js";
import { fetch as undiciFetch } from "undici";

// ---------------------------------------------------------------------------
// Wire types — snake_case per protocol §8.
// ---------------------------------------------------------------------------

interface WireDomain {
  name: string;
  version: string;
  chainId: number;
  verifyingContract: `0x${string}`;
}

interface WireReceipt {
  request_uuid: string;
  client_address: string;
  node_address: string;
  data_amount: number | string;
  total_price: number | string;
  tunnel_request_id?: string;
  created_at?: string;
}

interface PendingResponse {
  receipts: WireReceipt[];
  domain: WireDomain;
}

interface WireSignatureEntry {
  request_uuid: string;
  signature: `0x${string}`;
}

interface WireSignResponse {
  accepted: string[];
  rejected: Array<{ request_uuid: string; reason: string }>;
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ConsumerSettlementOptions {
  gatewayMgmtUrl: string;
  // TODO(track-c): swap stub for real ClientPaymentWallet from Track C.
  wallet: ClientPaymentWallet;
}

export interface PendingFetchResult {
  receipts: Receipt[];
  domain: EIP712Domain;
}

export interface SignatureSubmission {
  requestUuid: string;
  signature: `0x${string}`;
}

export interface SignatureSubmitResult {
  accepted: string[];
  rejected: Array<{ requestUuid: string; reason: string }>;
}

export interface SubmitOptions {
  strict?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse a wire `uint256` (number or decimal-string) as bigint per §8. */
function parseUint256(v: number | string): bigint {
  if (typeof v === "number") {
    if (!Number.isInteger(v) || v < 0) {
      throw new Error(`expected non-negative integer uint256, got ${v}`);
    }
    return BigInt(v);
  }
  return BigInt(v);
}

function decodeReceipt(raw: WireReceipt): Receipt {
  return {
    clientAddress: raw.client_address.toLowerCase() as `0x${string}`,
    nodeAddress: raw.node_address.toLowerCase() as `0x${string}`,
    requestUUID: raw.request_uuid,
    dataAmount: parseUint256(raw.data_amount),
    totalPrice: parseUint256(raw.total_price),
  };
}

function decodeDomain(raw: WireDomain): EIP712Domain {
  return {
    name: raw.name,
    version: raw.version,
    // Wire format is JSON number; Track C's eip712 domain typedata expects
    // bigint per viem's signTypedData signature.
    chainId: BigInt(raw.chainId),
    verifyingContract: raw.verifyingContract,
  };
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

// ---------------------------------------------------------------------------
// Bounded retry — protocol §9: 3 attempts, 200ms / 1s / 5s, retry on
// network errors and HTTP 5xx; surface body verbatim on final failure.
// ---------------------------------------------------------------------------

const RETRY_DELAYS_MS = [200, 1000, 5000] as const;

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface FetchAttemptResult {
  status: number;
  body: string;
}

async function fetchWithRetry(
  url: string,
  init: { method: string; headers?: Record<string, string>; body?: string },
): Promise<FetchAttemptResult> {
  let lastError: unknown;
  let lastResult: FetchAttemptResult | undefined;

  for (let attempt = 0; attempt < RETRY_DELAYS_MS.length; attempt += 1) {
    if (attempt > 0) {
      await sleep(RETRY_DELAYS_MS[attempt - 1]!);
    }

    try {
      const resp = await undiciFetch(url, {
        method: init.method,
        headers: init.headers,
        body: init.body,
      });
      const text = await resp.text();
      const result: FetchAttemptResult = { status: resp.status, body: text };

      if (resp.status >= 500 && resp.status < 600) {
        lastResult = result;
        continue;
      }
      return result;
    } catch (err) {
      // Network-level failure (TypeError per fetch spec, undici may also throw).
      if (err instanceof TypeError) {
        lastError = err;
        continue;
      }
      throw err;
    }
  }

  if (lastResult) return lastResult;
  throw lastError ?? new Error("fetchWithRetry exhausted with no result");
}

// ---------------------------------------------------------------------------
// ConsumerSettlementClient
// ---------------------------------------------------------------------------

export class ConsumerSettlementClient {
  private readonly _gatewayMgmtUrl: string;
  // TODO(track-c): swap stub for real ClientPaymentWallet from Track C.
  private readonly _wallet: ClientPaymentWallet;

  constructor(options: ConsumerSettlementOptions) {
    this._gatewayMgmtUrl = options.gatewayMgmtUrl.replace(/\/+$/, "");
    this._wallet = options.wallet;
  }

  // -------------------------------------------------------------------------
  // GET /leg1/pending
  // -------------------------------------------------------------------------

  async fetchPending(limit = 50): Promise<PendingFetchResult> {
    const addr = this._wallet.address.toLowerCase();
    const ts = nowSeconds();
    const message = `space-router:leg1-list-pending:${addr}:${ts}`;
    const sig = await this._wallet.signMessage(message);

    const qs = new URLSearchParams({
      address: addr,
      ts: String(ts),
      sig,
      limit: String(limit),
    });
    const url = `${this._gatewayMgmtUrl}/leg1/pending?${qs.toString()}`;

    const { status, body } = await fetchWithRetry(url, { method: "GET" });
    if (status < 200 || status >= 300) {
      throw new Error(
        `GET /leg1/pending failed: HTTP ${status} — ${body}`,
      );
    }

    const parsed = JSON.parse(body) as PendingResponse;
    return {
      receipts: (parsed.receipts ?? []).map(decodeReceipt),
      domain: decodeDomain(parsed.domain),
    };
  }

  // -------------------------------------------------------------------------
  // POST /leg1/sign
  // -------------------------------------------------------------------------

  async submitSignatures(
    sigs: SignatureSubmission[],
    opts?: SubmitOptions,
  ): Promise<SignatureSubmitResult> {
    const addr = this._wallet.address.toLowerCase();
    const ts = nowSeconds();
    const message = `space-router:leg1-sign:${addr}:${ts}`;
    const authSig = await this._wallet.signMessage(message);

    const wireSigs: WireSignatureEntry[] = sigs.map((s) => ({
      request_uuid: s.requestUuid,
      signature: s.signature,
    }));

    const body = JSON.stringify({
      address: addr,
      ts,
      sig: authSig,
      signatures: wireSigs,
    });

    const url = `${this._gatewayMgmtUrl}/leg1/sign`;
    const { status, body: respBody } = await fetchWithRetry(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });

    if (status < 200 || status >= 300) {
      throw new Error(
        `POST /leg1/sign failed: HTTP ${status} — ${respBody}`,
      );
    }

    const parsed = JSON.parse(respBody) as WireSignResponse;
    const result: SignatureSubmitResult = {
      accepted: parsed.accepted ?? [],
      rejected: (parsed.rejected ?? []).map((r) => ({
        requestUuid: r.request_uuid,
        reason: r.reason,
      })),
    };

    if (opts?.strict && result.rejected.length > 0) {
      throw new SettlementRejectedError(result.rejected);
    }
    return result;
  }

  // -------------------------------------------------------------------------
  // syncReceipts: fetch + sign + submit (one-shot)
  // -------------------------------------------------------------------------

  async syncReceipts(
    limit = 50,
    opts?: SubmitOptions,
  ): Promise<SignatureSubmitResult> {
    const { receipts, domain } = await this.fetchPending(limit);
    if (receipts.length === 0) {
      return { accepted: [], rejected: [] };
    }

    const sigs: SignatureSubmission[] = [];
    for (const receipt of receipts) {
      const signature = await this._wallet.signReceipt(receipt, domain);
      sigs.push({ requestUuid: receipt.requestUUID, signature });
    }
    return this.submitSignatures(sigs, opts);
  }
}
