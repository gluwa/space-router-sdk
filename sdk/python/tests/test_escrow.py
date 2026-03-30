"""Tests for SpaceRouter EscrowClient (SDK)."""
import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from spacerouter.escrow import (
    ESCROW_ABI,
    RECEIPT_EIP712_DOMAIN_NAME,
    RECEIPT_EIP712_DOMAIN_VERSION,
    EscrowClient,
)


@pytest.fixture
def mock_web3():
    """Mock Web3 and Account for EscrowClient tests."""
    with patch("web3.Web3") as MockWeb3, \
         patch("eth_account.Account") as MockAccount:
        w3_instance = MockWeb3.return_value
        w3_instance.to_checksum_address = lambda x: x
        w3_instance.eth.chain_id = 1
        w3_instance.eth.get_transaction_count.return_value = 0
        w3_instance.is_connected.return_value = True
        MockWeb3.HTTPProvider = MagicMock()

        contract_mock = MagicMock()
        w3_instance.eth.contract.return_value = contract_mock

        account_mock = MagicMock()
        account_mock.address = "0x" + "aa" * 20
        account_mock.key = b"\xab" * 32
        MockAccount.from_key.return_value = account_mock

        # spaceToken call raises to skip token init
        contract_mock.functions.spaceToken.return_value.call.side_effect = Exception("skip")

        yield {
            "Web3": MockWeb3,
            "Account": MockAccount,
            "w3": w3_instance,
            "contract": contract_mock,
            "account": account_mock,
        }


def _make_client(mock_web3) -> EscrowClient:
    """Create an EscrowClient with mocked web3."""
    return EscrowClient(
        rpc_url="http://localhost:8545",
        contract_address="0x" + "11" * 20,
        private_key="0x" + "ab" * 32,
    )


class TestEscrowBalance:
    def test_balance_query(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.escrowBalance.return_value.call.return_value = 50000
        assert client.balance("0x" + "cc" * 20) == 50000

    def test_balance_zero(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.escrowBalance.return_value.call.return_value = 0
        assert client.balance("0x" + "cc" * 20) == 0


class TestPendingWithdrawal:
    def test_pending_withdrawal(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.pendingWithdrawal.return_value.call.return_value = [1000, 1700000000]
        amount, unlock = client.pending_withdrawal("0x" + "cc" * 20)
        assert amount == 1000
        assert unlock == 1700000000

    def test_no_pending_withdrawal(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.pendingWithdrawal.return_value.call.return_value = [0, 0]
        amount, unlock = client.pending_withdrawal("0x" + "cc" * 20)
        assert amount == 0


class TestIsClaimed:
    def test_claimed_request(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.claimedRequests.return_value.call.return_value = True
        assert client.is_claimed("aabbccdd11223344aabbccdd11223344") is True

    def test_unclaimed_request(self, mock_web3):
        client = _make_client(mock_web3)
        mock_web3["contract"].functions.claimedRequests.return_value.call.return_value = False
        assert client.is_claimed("aabbccdd11223344aabbccdd11223344") is False


class TestWriteOperations:
    def test_deposit_requires_positive(self, mock_web3):
        client = _make_client(mock_web3)
        with pytest.raises(ValueError, match="positive"):
            client.deposit(0)

    def test_initiate_withdrawal_requires_positive(self, mock_web3):
        client = _make_client(mock_web3)
        with pytest.raises(ValueError, match="positive"):
            client.initiate_withdrawal(0)

    def test_read_only_client_rejects_writes(self, mock_web3):
        """Client without private key cannot write."""
        client = EscrowClient(
            rpc_url="http://localhost:8545",
            contract_address="0x" + "11" * 20,
            private_key=None,
        )
        with pytest.raises(RuntimeError, match="Private key required"):
            client.deposit(1000)


class TestSettleBatch:
    def test_settle_empty_file_raises(self, mock_web3):
        client = _make_client(mock_web3)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([], f)
            f.flush()
            with pytest.raises(ValueError, match="non-empty"):
                client.settle_batch(f.name)

    def test_settle_invalid_file_raises(self, mock_web3):
        client = _make_client(mock_web3)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"not": "an array"}, f)
            f.flush()
            with pytest.raises(ValueError, match="non-empty"):
                client.settle_batch(f.name)


class TestProperties:
    def test_address_with_key(self, mock_web3):
        client = _make_client(mock_web3)
        assert client.address == "0x" + "aa" * 20

    def test_address_without_key(self, mock_web3):
        client = EscrowClient(
            rpc_url="http://localhost:8545",
            contract_address="0x" + "11" * 20,
        )
        assert client.address == ""

    def test_contract_address(self, mock_web3):
        client = _make_client(mock_web3)
        assert client.contract_address == "0x" + "11" * 20


class TestEIP712:
    def test_domain_constants(self):
        assert RECEIPT_EIP712_DOMAIN_NAME == "SpaceRouterEscrow"
        assert RECEIPT_EIP712_DOMAIN_VERSION == "1"
