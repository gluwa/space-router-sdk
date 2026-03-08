"""
Node registration via Creditcoin stake verification + EIP-191 challenge-response.

Flow:
  1. POST /nodes/register/challenge  {address}
     → checks on-chain stake >= 1000 CTC, returns a random nonce (TTL 5 min)
  2. POST /nodes/register/verify  {address, endpoint_url, signed_nonce, ...}
     → ecrecovers signer, must match address
     → upserts the node row (creates or updates endpoint_url / public_ip)
"""

import logging
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from web3 import Web3
from eth_account.messages import encode_defunct

logger = logging.getLogger(__name__)

router = APIRouter(tags=["registration"])

# ---------------------------------------------------------------------------
# Creditcoin / staking config
# ---------------------------------------------------------------------------

RPC_URL = os.getenv("SR_CREDITCOIN_RPC_URL", "https://mainnet3.creditcoin.network")
CONTRACT_ADDRESS = os.getenv("SR_STAKING_CONTRACT_ADDRESS")  # set after deploy
MIN_STAKE_TOKENS = 1000
TOKEN_DECIMALS = 18
MIN_STAKE_WEI = MIN_STAKE_TOKENS * (10 ** TOKEN_DECIMALS)
NONCE_TTL = 300  # seconds

# Auto-getter ABI for: mapping(address => uint256) public stake;
STAKE_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "stake",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

w3 = Web3(Web3.HTTPProvider(RPC_URL))


# ---------------------------------------------------------------------------
# In-memory nonce store  (keyed by address_lower)
# ---------------------------------------------------------------------------
_nonces: dict[str, dict] = {}


def _purge_expired():
    now = int(time.time())
    expired = [a for a, v in _nonces.items() if v["expires"] < now]
    for a in expired:
        del _nonces[a]


# ---------------------------------------------------------------------------
# On-chain helper
# ---------------------------------------------------------------------------

def _get_staked_wei(address: str) -> int:
    if not CONTRACT_ADDRESS:
        raise HTTPException(
            status_code=500,
            detail="SR_STAKING_CONTRACT_ADDRESS env var not set",
        )
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONTRACT_ADDRESS),
            abi=STAKE_ABI,
        )
        return contract.functions.stake(Web3.to_checksum_address(address)).call()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Creditcoin RPC error: {e}")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChallengeRequest(BaseModel):
    address: str

class ChallengeResponse(BaseModel):
    nonce: str
    expires_in: int

class VerifyRequest(BaseModel):
    address: str
    endpoint_url: str
    signed_nonce: str
    label: Optional[str] = None
    region: Optional[str] = None

class VerifyResponse(BaseModel):
    status: str
    node_id: str
    address: str
    endpoint_url: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/nodes/register/challenge", response_model=ChallengeResponse)
async def request_challenge(body: ChallengeRequest):
    """Step 1: node requests a nonce. Stake is checked on-chain first."""
    address = body.address.strip().lower()

    if not Web3.is_address(address):
        raise HTTPException(status_code=400, detail="Invalid EVM address")

    staked_wei = _get_staked_wei(address)
    if staked_wei < MIN_STAKE_WEI:
        staked = staked_wei / (10 ** TOKEN_DECIMALS)
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient stake: {staked:.2f} CTC staked, {MIN_STAKE_TOKENS} CTC required",
        )

    _purge_expired()
    nonce = secrets.token_hex(32)
    _nonces[address] = {"nonce": nonce, "expires": int(time.time()) + NONCE_TTL}

    logger.info("Issued challenge nonce for %s", address)
    return ChallengeResponse(nonce=nonce, expires_in=NONCE_TTL)


@router.post("/nodes/register/verify", response_model=VerifyResponse)
async def verify_and_register(body: VerifyRequest, request: Request):
    """Step 2: node submits signed nonce + endpoint URL. Upserts nodes table."""
    address = body.address.strip().lower()

    if not Web3.is_address(address):
        raise HTTPException(status_code=400, detail="Invalid EVM address")

    _purge_expired()
    entry = _nonces.get(address)

    if not entry:
        raise HTTPException(
            status_code=400,
            detail="No pending challenge for this address — call /nodes/register/challenge first",
        )
    if int(time.time()) > entry["expires"]:
        del _nonces[address]
        raise HTTPException(status_code=400, detail="Challenge expired — request a new one")

    # Verify EIP-191 personal_sign signature
    try:
        message = encode_defunct(text=entry["nonce"])
        recovered = w3.eth.account.recover_message(message, signature=body.signed_nonce)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    if recovered.lower() != address:
        raise HTTPException(status_code=403, detail="Signature mismatch — wrong key or wrong nonce")

    # Consume nonce (one-time use)
    del _nonces[address]

    db = request.app.state.db

    # Upsert: find existing node for this address, update; otherwise insert
    existing = await db.select("nodes", params={"evm_address": address}, single=True)

    if existing:
        node_id = existing["id"]
        await db.update(
            "nodes",
            {"endpoint_url": body.endpoint_url, "label": body.label, "region": body.region},
            params={"id": node_id},
        )
        status = "updated"
        logger.info("Updated node %s for address %s", node_id, address)
    else:
        rows = await db.insert(
            "nodes",
            {
                "endpoint_url": body.endpoint_url,
                "node_type": "residential",
                "connectivity_type": "direct",
                "status": "online",
                "health_score": 1.0,
                "label": body.label,
                "region": body.region,
                "evm_address": address,
            },
            return_rows=True,
        )
        if not rows:
            raise HTTPException(status_code=500, detail="Failed to register node")
        node_id = rows[0]["id"]
        status = "registered"
        logger.info("Registered new node %s for address %s", node_id, address)

    return VerifyResponse(
        status=status,
        node_id=node_id,
        address=address,
        endpoint_url=body.endpoint_url,
    )
