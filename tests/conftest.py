from __future__ import annotations

import base64
import json

import pytest
from x402.schemas import (
    SettleResponse,
    SupportedKind,
    SupportedResponse,
    VerifyResponse,
)

TEST_NETWORK = "eip155:84532"
PAYER = "0x1111111111111111111111111111111111111111"
PAY_TO = "0x2222222222222222222222222222222222222222"
TX_HASH = "0x" + "ab" * 32


class FakeFacilitator:
    """In-process facilitator client double implementing the SDK protocol."""

    def __init__(self, *, valid: bool = True, settles: bool = True) -> None:
        self.valid = valid
        self.settles = settles
        self.verify_calls: list = []
        self.settle_calls: list = []

    async def verify(self, payload, requirements) -> VerifyResponse:
        self.verify_calls.append((payload, requirements))
        if not self.valid:
            return VerifyResponse(is_valid=False, invalid_reason="insufficient_funds")
        return VerifyResponse(is_valid=True, payer=PAYER)

    async def settle(self, payload, requirements) -> SettleResponse:
        self.settle_calls.append((payload, requirements))
        if not self.settles:
            return SettleResponse(
                success=False,
                error_reason="unexpected_settle_error",
                transaction="",
                network=TEST_NETWORK,
            )
        return SettleResponse(
            success=True,
            transaction=TX_HASH,
            network=TEST_NETWORK,
            payer=PAYER,
        )

    def get_supported(self) -> SupportedResponse:
        return SupportedResponse(
            kinds=[
                SupportedKind(x402_version=2, scheme="exact", network=TEST_NETWORK),
                SupportedKind(x402_version=1, scheme="exact", network="base-sepolia"),
            ]
        )


@pytest.fixture
def facilitator() -> FakeFacilitator:
    return FakeFacilitator()


def decode_payment_required(response) -> dict:
    """Decode the 402 challenge from the PAYMENT-REQUIRED header."""
    header = response.headers.get("PAYMENT-REQUIRED")
    assert header, f"no PAYMENT-REQUIRED header in {dict(response.headers)}"
    return json.loads(base64.b64decode(header))


def build_payment_header(payment_required: dict) -> str:
    """Build a structurally valid v2 PAYMENT-SIGNATURE header for the first
    accepted payment option (signature validity is the facilitator's concern,
    which the fake approves)."""
    accepted = payment_required["accepts"][0]
    payload = {
        "x402Version": 2,
        "resource": payment_required.get("resource"),
        "accepted": accepted,
        "payload": {
            "signature": "0x" + "11" * 65,
            "authorization": {
                "from": PAYER,
                "to": accepted["payTo"],
                "value": accepted["amount"],
                "validAfter": "0",
                "validBefore": "99999999999",
                "nonce": "0x" + "22" * 32,
            },
        },
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()
