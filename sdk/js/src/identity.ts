/**
 * Node identity keypair management for the SpaceRouter JS SDK.
 *
 * Generates and persists a secp256k1 keypair used for signing authenticated
 * API requests.  Default storage: `~/.spacerouter/identity.key`.
 */

import {
  privateKeyToAccount,
  generatePrivateKey,
} from "viem/accounts";
import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  existsSync,
  chmodSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const DEFAULT_IDENTITY_PATH = join(
  homedir(),
  ".spacerouter",
  "identity.key",
);

/**
 * Load or generate a secp256k1 identity keypair.
 *
 * Returns `{ privateKey, address }`.
 */
export function loadOrCreateIdentity(
  keyPath: string = DEFAULT_IDENTITY_PATH,
): { privateKey: `0x${string}`; address: string } {
  if (existsSync(keyPath)) {
    const raw = readFileSync(keyPath, "utf-8").trim();
    const privateKey = (
      raw.startsWith("0x") ? raw : `0x${raw}`
    ) as `0x${string}`;
    const account = privateKeyToAccount(privateKey);
    return { privateKey, address: account.address.toLowerCase() };
  }

  const privateKey = generatePrivateKey();
  const account = privateKeyToAccount(privateKey);

  mkdirSync(dirname(keyPath), { recursive: true });
  writeFileSync(keyPath, privateKey + "\n", { mode: 0o600 });
  try {
    chmodSync(keyPath, 0o600);
  } catch {
    // chmod may fail on some platforms — best-effort
  }

  return { privateKey, address: account.address.toLowerCase() };
}

/** Derive the lowercase Ethereum address from a private key. */
export function getAddress(privateKey: `0x${string}`): string {
  return privateKeyToAccount(privateKey).address.toLowerCase();
}

/**
 * Sign a Space Router API request using EIP-191.
 *
 * Message format: `space-router:{action}:{target}:{timestamp}`
 *
 * Returns `{ signature, timestamp }`.
 */
export async function signRequest(
  privateKey: `0x${string}`,
  action: string,
  target: string,
): Promise<{ signature: string; timestamp: number }> {
  const timestamp = Math.floor(Date.now() / 1000);
  const message = `space-router:${action}:${target}:${timestamp}`;
  const account = privateKeyToAccount(privateKey);
  const signature = await account.signMessage({ message });
  return { signature, timestamp };
}

/**
 * Sign a vouching message: identity wallet vouches for staking + collection wallets.
 *
 * Message format: `space-router:vouch:{stakingAddress}:{collectionAddress}:{timestamp}`
 *
 * Returns `{ signature, timestamp }`.
 */
export async function createVouchingSignature(
  privateKey: `0x${string}`,
  stakingAddress: string,
  collectionAddress: string,
): Promise<{ signature: string; timestamp: number }> {
  const timestamp = Math.floor(Date.now() / 1000);
  const message = `space-router:vouch:${stakingAddress.toLowerCase()}:${collectionAddress.toLowerCase()}:${timestamp}`;
  const account = privateKeyToAccount(privateKey);
  const signature = await account.signMessage({ message });
  return { signature, timestamp };
}


// ---------------------------------------------------------------------------
// Client Identity Wallet (v0.2.0)
// ---------------------------------------------------------------------------

/**
 * Client-side identity wallet for wallet-authenticated requests.
 *
 * The private key is encapsulated inside a viem Account object and is never
 * exposed as a string property.
 *
 * @example
 * ```ts
 * const identity = ClientIdentity.generate();
 * const headers = await identity.signAuthHeaders();
 * ```
 */
export class ClientIdentity {
  private _account: ReturnType<typeof privateKeyToAccount>;
  private _keyHex: `0x${string}`;
  private _paymentAddress?: string;

  private constructor(account: ReturnType<typeof privateKeyToAccount>, keyHex: `0x${string}`) {
    this._account = account;
    this._keyHex = keyHex;
  }

  /** Create from a raw private key. */
  static fromPrivateKey(privateKey: `0x${string}`): ClientIdentity {
    return new ClientIdentity(privateKeyToAccount(privateKey), privateKey);
  }

  /**
   * Generate a new identity wallet.
   * If `keystorePath` is provided, saves the key to disk.
   */
  static generate(keystorePath?: string): ClientIdentity {
    const privKey = generatePrivateKey();
    const instance = new ClientIdentity(privateKeyToAccount(privKey), privKey);
    if (keystorePath) {
      instance.saveKeystore(keystorePath);
    }
    return instance;
  }

  /**
   * Load from a plaintext key file.
   * For encrypted keystore files, decrypt externally and use `fromPrivateKey()`.
   */
  static fromKeystore(path: string): ClientIdentity {
    const raw = readFileSync(path, "utf-8").trim();
    const privKey = (raw.startsWith("0x") ? raw : `0x${raw}`) as `0x${string}`;
    return new ClientIdentity(privateKeyToAccount(privKey), privKey);
  }

  /** Identity address (lowercase, 0x-prefixed). */
  get address(): string {
    return this._account.address.toLowerCase();
  }

  /** Optional payment wallet address. */
  get paymentAddress(): string | undefined {
    return this._paymentAddress;
  }

  set paymentAddress(address: string) {
    this._paymentAddress = address.toLowerCase();
  }

  /** EIP-191 sign a message. Returns hex signature. */
  async signMessage(message: string): Promise<string> {
    return this._account.signMessage({ message });
  }

  /**
   * Generate auth headers for Coordination API requests.
   *
   * Returns headers: `X-Identity-Address`, `X-Identity-Signature`, `X-Timestamp`.
   *
   * Server-side timestamp validation window is ±300 seconds.
   */
  async signAuthHeaders(
    timestamp?: number,
  ): Promise<Record<string, string>> {
    const ts = timestamp ?? Math.floor(Date.now() / 1000);
    const message = `space-router:auth:${this.address}:${ts}`;
    const signature = await this.signMessage(message);
    return {
      "X-Identity-Address": this.address,
      "X-Identity-Signature": signature,
      "X-Timestamp": String(ts),
    };
  }

  /** Save key to a plaintext file (0o600 permissions). */
  saveKeystore(path: string): void {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, this._keyHex + "\n", { mode: 0o600 });
    try {
      chmodSync(path, 0o600);
    } catch {
      // chmod may fail on some platforms
    }
  }
}
