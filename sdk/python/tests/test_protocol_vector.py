"""Cross-stack EIP-712 canonical vector test.

Pins the signature defined in §7 of
``internal-docs/v1.5-consumer-protocol.md``. This is the join point
between the Python and JS implementations — every SDK CI run MUST
recompute and assert this signature byte-identically. Any drift here
indicates an interop break.
"""

from __future__ import annotations

from eth_account import Account

from spacerouter.payment.eip712 import (
    EIP712Domain,
    Receipt,
    recover_receipt_signer,
    sign_receipt,
)


# Canonical vector from v1.5-consumer-protocol.md §7
PRIVATE_KEY = "0x3658361ca2257090f7b4bc44d7b514f930b038cd368050fc45ae7849f55a7937"
EXPECTED_ADDRESS = "0x61F5B13A42016D94AdEaC2857f77cc7cd9f0e11C"
EXPECTED_SIGNATURE = (
    "0x15cbab3e32932fdfc01ebfb712b34ef1970f9b7b6e08318aea414ca1dbd4a2bf"
    "04d5812dda908013e42091ae473667dfbf6110432e1f4e3ee7b9543916c61dd41c"
)

DOMAIN = EIP712Domain(
    name="TokenPaymentEscrow",
    version="1",
    chain_id=102031,
    verifying_contract="0xC5740e4e9175301a24FB6d22bA184b8ec0762852",
)

# bytes32 zero-padded form of 0x9e46051b44b1639a8a9f8a53041c6f121c0fe789
NODE_ADDRESS_BYTES32 = (
    "0x0000000000000000000000009e46051b44b1639a8a9f8a53041c6f121c0fe789"
)

RECEIPT = Receipt(
    client_address=EXPECTED_ADDRESS,
    node_address=NODE_ADDRESS_BYTES32,
    request_uuid="00000000-0000-0000-0000-000000000001",
    data_amount=1024,
    total_price=1000000000000000,
)


def test_canonical_signature_matches() -> None:
    """sign_receipt must produce the exact pinned signature."""
    # Sanity: the private key really does map to the expected address.
    assert Account.from_key(PRIVATE_KEY).address == EXPECTED_ADDRESS

    sig = sign_receipt(PRIVATE_KEY, RECEIPT, DOMAIN)
    assert sig == EXPECTED_SIGNATURE, (
        "EIP-712 canonical vector drift! "
        f"expected={EXPECTED_SIGNATURE} got={sig}. "
        "This breaks JS/Python interop — see §7 of v1.5-consumer-protocol.md."
    )


def test_canonical_signature_recovers_to_expected_signer() -> None:
    """recover_receipt_signer must round-trip to the expected address."""
    recovered = recover_receipt_signer(RECEIPT, EXPECTED_SIGNATURE, DOMAIN)
    assert recovered == EXPECTED_ADDRESS
