/**
 * ProxyAgent that captures CONNECT response headers (X-SpaceRouter-Node, etc.).
 *
 * For HTTPS target URLs, the gateway sends X-SpaceRouter-Node on the
 * CONNECT 200 OK response — but undici's stock {@link ProxyAgent} consumes
 * the CONNECT response internally and only surfaces { socket, statusCode }
 * to its caller, dropping the headers entirely. The result was that
 * `ProxyResponse.nodeId` returned `undefined` for HTTPS proxied requests
 * (the typical case), even after the SDK fetch'd a successful response.
 *
 * undici's public `Pool#connect()` API (api-connect.js) DOES return
 * `{ statusCode, headers, socket, ... }` from the CONNECT — we just need
 * to intercept the call. {@link ProxyAgent.Options} accepts a
 * `clientFactory` hook that constructs the proxy-side Pool; we use it to
 * wrap `pool.connect()` and stash the headers on the agent instance.
 *
 * After `fetch()` returns, the SDK reads `agent.lastNodeId` /
 * `agent.lastRequestId` and stamps them onto the ProxyResponse.
 *
 * Concurrency: for paid requests, the SDK constructs one of these per
 * request, so capture is 1:1 with the call. For shared/long-lived agents
 * (non-paid path), undici may reuse a CONNECT tunnel across requests to
 * the same target — `lastNodeId` then reflects the tunnel's bound node
 * (correct, since the gateway routes whole tunnels to a single node).
 */

import { Pool, ProxyAgent } from "undici";

export interface ConnectMetadata {
  nodeId?: string;
  requestId?: string;
  routingTag?: string;
}

/** Lower-cased subset of the CONNECT response headers we care about. */
const HEADER_NODE_ID = "x-spacerouter-node";
const HEADER_REQUEST_ID = "x-spacerouter-request-id";
const HEADER_ROUTING_TAG = "x-spacerouter-routing";

/**
 * undici's CONNECT result returns headers as either an object
 * (`Record<string, string | string[]>`) or — when the caller requests
 * `responseHeaders: 'raw'` — a `Buffer[]`. We only need the object form;
 * the SDK never enables raw mode.
 */
type ConnectHeaders = Record<string, string | string[] | undefined>;

function pickHeader(
  headers: ConnectHeaders | null | undefined,
  name: string,
): string | undefined {
  if (!headers) return undefined;
  // undici lowercases header names in object form. Defensive extra checks
  // keep us safe against future internal changes.
  const v = headers[name] ?? headers[name.toLowerCase()];
  if (v == null) return undefined;
  return Array.isArray(v) ? v[0] : v;
}

export class CapturingProxyAgent extends ProxyAgent {
  /** Most recent CONNECT response's X-SpaceRouter-Node header (lowercased). */
  public lastNodeId?: string;
  /** Most recent CONNECT response's X-SpaceRouter-Request-Id header. */
  public lastRequestId?: string;
  /** "home" or "fallback" — emitted by the gateway alongside the node id. */
  public lastRoutingTag?: string;

  constructor(opts: ProxyAgent.Options) {
    super({
      ...opts,
      clientFactory: (origin, options) => {
        // The proxy-agent invokes this factory once per origin to create
        // its proxy-side dispatcher. We wrap the resulting Pool so that
        // each `connect()` call (the CONNECT step for HTTPS tunnels)
        // surfaces its response headers to us before returning the
        // socket/status pair undici cares about.
        const pool = new Pool(origin, options);
        const original = pool.connect.bind(pool);
        // undici's connect signature accepts (opts) → Promise OR
        // (opts, callback). The proxy-agent uses the promise form
        // internally (see proxy-agent.js:195), so we only override that
        // path. Callback form is preserved by delegating verbatim.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const wrapped = (opts2: any, cb?: any): any => {
          if (typeof cb === "function") {
            return original(opts2, (err: Error | null, data: unknown) => {
              if (!err && data && typeof data === "object") {
                this._captureFromConnect(
                  (data as { headers?: ConnectHeaders }).headers,
                );
              }
              return cb(err, data);
            });
          }
          // Promise form
          return original(opts2).then((result: unknown) => {
            if (result && typeof result === "object") {
              this._captureFromConnect(
                (result as { headers?: ConnectHeaders }).headers,
              );
            }
            return result;
          });
        };
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (pool as any).connect = wrapped;
        return pool;
      },
    });
  }

  /** Read the SR headers off a CONNECT response and stash on the agent. */
  private _captureFromConnect(
    headers: ConnectHeaders | null | undefined,
  ): void {
    const nodeId = pickHeader(headers, HEADER_NODE_ID);
    const requestId = pickHeader(headers, HEADER_REQUEST_ID);
    const routingTag = pickHeader(headers, HEADER_ROUTING_TAG);
    if (nodeId !== undefined) this.lastNodeId = nodeId;
    if (requestId !== undefined) this.lastRequestId = requestId;
    if (routingTag !== undefined) this.lastRoutingTag = routingTag;
  }

  /** Snapshot of the most recent CONNECT capture. */
  public capturedMetadata(): ConnectMetadata {
    return {
      nodeId: this.lastNodeId,
      requestId: this.lastRequestId,
      routingTag: this.lastRoutingTag,
    };
  }
}
