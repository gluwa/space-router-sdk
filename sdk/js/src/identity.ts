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
 * Sign a vouching message: identity wallet vouches for staking wallet.
 *
 * Message format: `space-router:vouch:{stakingAddress}:{timestamp}`
 *
 * Returns `{ signature, timestamp }`.
 */
export async function createVouchingSignature(
  privateKey: `0x${string}`,
  stakingAddress: string,
): Promise<{ signature: string; timestamp: number }> {
  const timestamp = Math.floor(Date.now() / 1000);
  const message = `space-router:vouch:${stakingAddress.toLowerCase()}:${timestamp}`;
  const account = privateKeyToAccount(privateKey);
  const signature = await account.signMessage({ message });
  return { signature, timestamp };
}
