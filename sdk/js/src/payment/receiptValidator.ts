/**
 * Client receipt validation for v0.2.3 SPACE payments.
 *
 * Validates receipts received from the gateway before signing them.
 * Implements 5 validation checks plus timestamp validation.
 * @module payment/receiptValidator
 */

/** Maximum allowed timestamp drift (5 minutes). */
const MAX_TIMESTAMP_DRIFT = 300;
const ZERO_ADDRESS = "0x" + "0".repeat(40);
const GB = BigInt(1024 ** 3);

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface ReceiptData {
  clientPaymentAddress: string;
  nodeCollectionAddress: string;
  requestId: string;
  dataBytes: number | bigint;
  priceWei: number | bigint;
  timestamp: number | bigint;
}

export interface ReceiptValidatorOptions {
  /** Our client payment address (for check #1). */
  clientAddress: string;
  /** Maximum acceptable rate per GB in wei (0 = no limit). */
  maxRatePerGbWei?: bigint;
  /** Maximum allowed timestamp drift in seconds. */
  maxTimestampDrift?: number;
}

/**
 * Validates receipts from the gateway before the client signs them.
 *
 * Performs the following checks:
 * 1. Client payment address matches our wallet
 * 2. Node collection address is not zero/empty
 * 3. Request ID is not empty
 * 4. Data bytes are non-negative
 * 5. Price is reasonable (within expected rate bounds)
 * 6. Timestamp is within acceptable drift
 */
export class ReceiptValidator {
  private clientAddress: string;
  private maxRatePerGbWei: bigint;
  private maxTimestampDrift: number;

  constructor(options: ReceiptValidatorOptions) {
    this.clientAddress = options.clientAddress.toLowerCase();
    this.maxRatePerGbWei = options.maxRatePerGbWei ?? 0n;
    this.maxTimestampDrift = options.maxTimestampDrift ?? MAX_TIMESTAMP_DRIFT;
  }

  /**
   * Validate a receipt received from the gateway.
   */
  validate(receipt: ReceiptData): ValidationResult {
    const errors: string[] = [];

    // Check 1: Client payment address matches our wallet
    const clientAddr = receipt.clientPaymentAddress?.toLowerCase() ?? "";
    if (clientAddr !== this.clientAddress) {
      errors.push(
        `Client address mismatch: expected ${this.clientAddress}, got ${clientAddr}`,
      );
    }

    // Check 2: Node collection address is valid
    const nodeAddr = receipt.nodeCollectionAddress ?? "";
    if (!nodeAddr || nodeAddr === ZERO_ADDRESS) {
      errors.push("Node collection address is empty or zero");
    }

    // Check 3: Request ID is present
    if (!receipt.requestId) {
      errors.push("Request ID is empty");
    }

    // Check 4: Data bytes are non-negative
    const dataBytes = BigInt(receipt.dataBytes ?? -1);
    if (dataBytes < 0n) {
      errors.push(`Data bytes is negative: ${dataBytes}`);
    }

    // Check 5: Price is reasonable
    const priceWei = BigInt(receipt.priceWei ?? -1);
    if (priceWei < 0n) {
      errors.push(`Price is negative: ${priceWei}`);
    } else if (this.maxRatePerGbWei > 0n && dataBytes > 0n) {
      const maxPrice = (dataBytes * this.maxRatePerGbWei) / GB;
      if (priceWei > maxPrice * 2n) {
        errors.push(
          `Price ${priceWei} exceeds maximum expected ${maxPrice} for ${dataBytes} bytes`,
        );
      }
    }

    // Check 6: Timestamp is within acceptable drift
    const timestamp = Number(receipt.timestamp ?? 0);
    const now = Math.floor(Date.now() / 1000);
    const drift = Math.abs(now - timestamp);
    if (drift > this.maxTimestampDrift) {
      errors.push(
        `Timestamp drift too large: ${drift}s (max ${this.maxTimestampDrift}s)`,
      );
    }

    return { valid: errors.length === 0, errors };
  }
}
