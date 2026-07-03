from __future__ import annotations

import base64
import json as jsonlib

from sanic import Sanic
from sanic.response import json

from sanic_x402 import X402, paid

from .conftest import (
    PAY_TO,
    TEST_NETWORK,
    TX_HASH,
    build_payment_header,
    decode_payment_required,
)


def make_app(facilitator, **x402_kwargs) -> Sanic:
    app = Sanic("TestApp")
    app.config.TOUCHUP = False
    X402(
        app,
        pay_to=PAY_TO,
        network=TEST_NETWORK,
        facilitator=facilitator,
        **x402_kwargs,
    )

    @app.get("/free")
    async def free(request):
        return json({"free": True})

    @app.get("/premium")
    @paid("$0.01")
    async def premium(request):
        """Premium market data."""
        payer_info = request.ctx.x402
        return json({"premium": True, "has_payment": payer_info is not None})

    @app.get("/kwarg-priced", ctx_x402="$0.05")
    async def kwarg_priced(request):
        return json({"ok": True})

    @app.get("/flaky")
    @paid("$0.01")
    async def flaky(request):
        return json({"error": "boom"}, status=500)

    return app


def test_free_route_untouched(facilitator):
    app = make_app(facilitator)
    _, response = app.test_client.get("/free")
    assert response.status == 200
    assert response.json == {"free": True}
    assert not facilitator.verify_calls


def test_unpaid_request_gets_402_challenge(facilitator):
    app = make_app(facilitator)
    _, response = app.test_client.get("/premium")
    assert response.status == 402

    challenge = decode_payment_required(response)
    assert challenge["x402Version"] == 2
    option = challenge["accepts"][0]
    assert option["scheme"] == "exact"
    assert option["network"] == TEST_NETWORK
    assert option["payTo"] == PAY_TO
    assert int(option["amount"]) > 0  # "$0.01" resolved to atomic units
    # Description defaults to the handler docstring
    assert challenge["resource"]["description"] == "Premium market data."


def test_paid_request_serves_resource_and_settles(facilitator):
    app = make_app(facilitator)
    _, challenge_response = app.test_client.get("/premium")
    header = build_payment_header(decode_payment_required(challenge_response))

    _, response = app.test_client.get(
        "/premium", headers={"PAYMENT-SIGNATURE": header}
    )
    assert response.status == 200
    assert response.json == {"premium": True, "has_payment": True}

    assert len(facilitator.verify_calls) == 1
    assert len(facilitator.settle_calls) == 1

    settlement_header = response.headers.get("PAYMENT-RESPONSE")
    assert settlement_header
    settlement = jsonlib.loads(base64.b64decode(settlement_header))
    assert settlement["success"] is True
    assert settlement["transaction"] == TX_HASH


def test_invalid_payment_rejected(facilitator):
    facilitator.valid = False
    app = make_app(facilitator)
    _, challenge_response = app.test_client.get("/premium")
    header = build_payment_header(decode_payment_required(challenge_response))

    _, response = app.test_client.get(
        "/premium", headers={"PAYMENT-SIGNATURE": header}
    )
    assert response.status == 402
    assert not facilitator.settle_calls


def test_error_response_is_not_settled(facilitator):
    app = make_app(facilitator)
    _, challenge_response = app.test_client.get("/premium")
    # Reuse the same option shape; /flaky has identical requirements
    header = build_payment_header(decode_payment_required(challenge_response))

    _, response = app.test_client.get("/flaky", headers={"PAYMENT-SIGNATURE": header})
    assert response.status == 500
    assert not facilitator.settle_calls


def test_settlement_failure_returns_402(facilitator):
    facilitator.settles = False
    app = make_app(facilitator)
    _, challenge_response = app.test_client.get("/premium")
    header = build_payment_header(decode_payment_required(challenge_response))

    _, response = app.test_client.get(
        "/premium", headers={"PAYMENT-SIGNATURE": header}
    )
    assert response.status == 402


def test_ctx_kwarg_route_is_gated(facilitator):
    app = make_app(facilitator)
    _, response = app.test_client.get("/kwarg-priced")
    assert response.status == 402
    challenge = decode_payment_required(response)
    assert challenge["accepts"][0]["payTo"] == PAY_TO
