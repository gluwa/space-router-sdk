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
import {
  scryptSync,
  randomBytes,
  createCipheriv,
  createDecipheriv,
  createHash,
} from "node:crypto";

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
  // True ES2022 private field: inaccessible from outside the class at runtime,
  // not just at TypeScript compile time.  This prevents accidental key leakage
  // via serialisation, Object.keys(), JSON.stringify(), or property enumeration.
  #privateKey: `0x${string}`;
  private _address: string;
  private _paymentAddress?: string;

  private constructor(account: ReturnType<typeof privateKeyToAccount>, keyHex: `0x${string}`) {
    this._account = account;
    this.#privateKey = keyHex;
    // Cache lowercased address — avoids a .toLowerCase() allocation on every
    // property access and every signAuthHeaders() call.
    this._address = account.address.toLowerCase();
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
   * Load from a plaintext key file or encrypted Web3 keystore JSON.
   *
   * If the file contains an encrypted keystore (has `crypto`/`Crypto` key),
   * a passphrase is required.
   */
  static fromKeystore(path: string, passphrase?: string): ClientIdentity {
    const raw = readFileSync(path, "utf-8").trim();

    // Try JSON keystore
    try {
      const data = JSON.parse(raw);
      if (data && typeof data === "object" && ("crypto" in data || "Crypto" in data)) {
        if (!passphrase) {
          throw new Error(`Keystore at '${path}' is encrypted — passphrase required.`);
        }
        const cryptoObj = data.crypto ?? data.Crypto;
        const kdfParams = cryptoObj.kdfparams;
        const derivedKey = scryptSync(
          Buffer.from(passphrase, "utf-8"),
          Buffer.from(kdfParams.salt, "hex"),
          kdfParams.dklen,
          { N: kdfParams.n, r: kdfParams.r, p: kdfParams.p, maxmem: 512 * 1024 * 1024 },
        );
        // Verify MAC
        const ciphertext = Buffer.from(cryptoObj.ciphertext, "hex");
        const macInput = Buffer.concat([derivedKey.subarray(16, 32), ciphertext]);
        const mac = createHash("sha3-256").update(macInput).digest("hex");
        if (mac !== cryptoObj.mac) {
          throw new Error("Wrong passphrase — MAC mismatch.");
        }
        const iv = Buffer.from(cryptoObj.cipherparams.iv, "hex");
        const decipher = createDecipheriv("aes-128-ctr", derivedKey.subarray(0, 16), iv);
        const keyBytes = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
        const privKey = `0x${keyBytes.toString("hex")}` as `0x${string}`;
        return new ClientIdentity(privateKeyToAccount(privKey), privKey);
      }
    } catch (e) {
      if (e instanceof SyntaxError) {
        // Not JSON — fall through to raw hex
      } else {
        throw e;
      }
    }

    const privKey = (raw.startsWith("0x") ? raw : `0x${raw}`) as `0x${string}`;
    return new ClientIdentity(privateKeyToAccount(privKey), privKey);
  }

  /** Identity address (lowercase, 0x-prefixed). */
  get address(): string {
    return this._address;
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
    if (typeof ts !== "number" || !Number.isFinite(ts)) {
      throw new TypeError(`timestamp must be a finite number, got ${ts}`);
    }
    const message = `space-router:auth:${this.address}:${ts}`;
    const signature = await this.signMessage(message);
    return {
      "X-Identity-Address": this.address,
      "X-Identity-Signature": signature,
      "X-Timestamp": String(ts),
    };
  }

  /**
   * Save key to disk. If `passphrase` is provided, encrypts using Web3
   * secret storage format (scrypt + aes-128-ctr). Otherwise plaintext.
   */
  saveKeystore(path: string, passphrase?: string): void {
    mkdirSync(dirname(path), { recursive: true });
    if (passphrase) {
      const keyBytes = Buffer.from(this.#privateKey.slice(2), "hex");
      const salt = randomBytes(32);
      const iv = randomBytes(16);
      const kdfParams = { dklen: 32, n: 262144, r: 8, p: 1, salt: salt.toString("hex") };
      const derivedKey = scryptSync(
        Buffer.from(passphrase, "utf-8"),
        salt,
        kdfParams.dklen,
        { N: kdfParams.n, r: kdfParams.r, p: kdfParams.p, maxmem: 512 * 1024 * 1024 },
      );
      const cipher = createCipheriv("aes-128-ctr", derivedKey.subarray(0, 16), iv);
      const ciphertext = Buffer.concat([cipher.update(keyBytes), cipher.final()]);
      const macInput = Buffer.concat([derivedKey.subarray(16, 32), ciphertext]);
      const mac = createHash("sha3-256").update(macInput).digest("hex");
      const keystore = {
        version: 3,
        id: randomBytes(16).toString("hex"),
        address: this._address.slice(2),
        crypto: {
          cipher: "aes-128-ctr",
          cipherparams: { iv: iv.toString("hex") },
          ciphertext: ciphertext.toString("hex"),
          kdf: "scrypt",
          kdfparams: kdfParams,
          mac,
        },
      };
      writeFileSync(path, JSON.stringify(keystore), { mode: 0o600 });
    } else {
      writeFileSync(path, this.#privateKey + "\n", { mode: 0o600 });
    }
    try {
      chmodSync(path, 0o600);
    } catch {
      // chmod may fail on some platforms
    }
  }
}
