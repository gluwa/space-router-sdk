"""SpaceRouter payment SDK for Consumer SPACE-token proxy payments."""

from spacerouter.payment.client_wallet import ClientPaymentWallet
from spacerouter.payment.consumer_settlement import ConsumerSettlementClient
from spacerouter.payment.eip712 import EIP712Domain, Receipt
from spacerouter.payment.spacecoin_client import SpaceRouterSPACE

__all__ = [
    "ClientPaymentWallet",
    "ConsumerSettlementClient",
    "EIP712Domain",
    "EscrowClient",
    "Receipt",
    "SpaceRouterSPACE",
]


def __getattr__(name: str):
    """Lazy re-export of EscrowClient.

    EscrowClient lives at ``spacerouter.escrow`` but is conceptually part of
    the payment surface — users reasonably try ``from spacerouter.payment
    import EscrowClient``. We do this lazily because escrow.py imports
    ``spacerouter.payment.eip712``, so an eager ``from spacerouter.escrow
    import EscrowClient`` here would create a circular import.
    """
    if name == "EscrowClient":
        from spacerouter.escrow import EscrowClient as _EscrowClient
        return _EscrowClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
