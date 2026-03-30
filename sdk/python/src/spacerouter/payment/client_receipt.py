"""Client receipt validation for v0.2.3 SPACE payments.

Validates receipts received from the gateway before signing them.
Implements 5 validation checks plus timestamp validation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum allowed timestamp drift (5 minutes)
MAX_TIMESTAMP_DRIFT = 300


@dataclass
class ValidationResult:
    """Result of receipt validation."""

    valid: bool
    errors: list[str]

    def __bool__(self) -> bool:
        return self.valid


class ClientReceiptValidator:
    """Validates receipts from the gateway before the client signs them.

    Performs the following checks:
    1. Client payment address matches our wallet
    2. Node collection address is not zero/empty
    3. Request ID is not empty
    4. Data bytes are non-negative
    5. Price is reasonable (within expected rate bounds)
    6. Timestamp is within acceptable drift
    """

    def __init__(
        self,
        client_address: str,
        max_rate_per_gb_wei: int = 0,
        max_timestamp_drift: int = MAX_TIMESTAMP_DRIFT,
    ):
        """
        Parameters
        ----------
        client_address : str
            Our client payment address (for check #1).
        max_rate_per_gb_wei : int
            Maximum acceptable rate per GB in wei (0 = no limit).
        max_timestamp_drift : int
            Maximum allowed timestamp drift in seconds.
        """
        self.client_address = client_address.lower()
        self.max_rate_per_gb_wei = max_rate_per_gb_wei
        self.max_timestamp_drift = max_timestamp_drift

    def validate(self, receipt: dict) -> ValidationResult:
        """Validate a receipt received from the gateway.

        Parameters
        ----------
        receipt : dict
            Receipt with keys: clientPaymentAddress, nodeCollectionAddress,
            requestId, dataBytes, priceWei, timestamp.

        Returns
        -------
        ValidationResult
            Result with valid flag and list of errors.
        """
        errors: list[str] = []

        # Check 1: Client payment address matches our wallet
        client_addr = receipt.get("clientPaymentAddress", "")
        if client_addr.lower() != self.client_address:
            errors.append(
                f"Client address mismatch: expected {self.client_address}, "
                f"got {client_addr.lower()}"
            )

        # Check 2: Node collection address is valid
        node_addr = receipt.get("nodeCollectionAddress", "")
        if not node_addr or node_addr == "0x" + "0" * 40:
            errors.append("Node collection address is empty or zero")

        # Check 3: Request ID is present
        request_id = receipt.get("requestId", "")
        if not request_id:
            errors.append("Request ID is empty")

        # Check 4: Data bytes are non-negative
        data_bytes = receipt.get("dataBytes", -1)
        try:
            data_bytes = int(data_bytes)
            if data_bytes < 0:
                errors.append(f"Data bytes is negative: {data_bytes}")
        except (ValueError, TypeError):
            errors.append(f"Invalid data bytes value: {data_bytes}")

        # Check 5: Price is reasonable
        price_wei = receipt.get("priceWei", -1)
        try:
            price_wei = int(price_wei)
            if price_wei < 0:
                errors.append(f"Price is negative: {price_wei}")
            elif self.max_rate_per_gb_wei > 0 and data_bytes > 0:
                # Verify price doesn't exceed maximum rate
                max_price = (data_bytes * self.max_rate_per_gb_wei) // (1024 ** 3)
                if price_wei > max_price * 2:  # 2x buffer for rounding
                    errors.append(
                        f"Price {price_wei} exceeds maximum expected "
                        f"{max_price} for {data_bytes} bytes"
                    )
        except (ValueError, TypeError):
            errors.append(f"Invalid price value: {price_wei}")

        # Check 6: Timestamp is within acceptable drift
        timestamp = receipt.get("timestamp", 0)
        try:
            timestamp = int(timestamp)
            now = int(time.time())
            drift = abs(now - timestamp)
            if drift > self.max_timestamp_drift:
                errors.append(
                    f"Timestamp drift too large: {drift}s "
                    f"(max {self.max_timestamp_drift}s)"
                )
        except (ValueError, TypeError):
            errors.append(f"Invalid timestamp value: {timestamp}")

        return ValidationResult(valid=len(errors) == 0, errors=errors)
