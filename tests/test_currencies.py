from __future__ import annotations

import pytest
from sanic import Sanic
from sanic.response import json

from sanic_x402 import X402, AssetAmount, paid
from sanic_x402.extension import _to_asset_amount

from .conftest import PAY_TO, TEST_NETWORK, decode_payment_required

EURC = "0x808456652fdb597867f38412077A9182bf77359F"


def test_to_asset_amount_formats():
    for price, expected in [
        ("0.50", "500000"),
        ("€0.50", "500000"),
        ("$0.50", "500000"),
        ("0.50 EURC", "500000"),
        (0.5, "500000"),
        (2, "2000000"),
    ]:
        result = _to_asset_amount(price, EURC, 6, None)
        assert result.amount == expected, price
        assert result.asset == EURC

    # 18-decimal assets convert without float loss
    assert _to_asset_amount("1.5", "0xToken", 18, None).amount == str(
        15 * 10**17
    )

    # An existing AssetAmount passes through untouched
    existing = AssetAmount(amount="123", asset=EURC)
    assert _to_asset_amount(existing, EURC, 6, None) is existing


def test_custom_asset_route_challenge(facilitator):
    app = Sanic("CurrencyApp")
    app.config.TOUCHUP = False
    X402(app, pay_to=PAY_TO, network=TEST_NETWORK, facilitator=facilitator)

    @app.get("/eurc")
    @paid(
        "€0.50",
        asset=EURC,
        asset_extra={"name": "EURC", "version": "2"},
    )
    async def eurc_route(request):
        return json({"ok": True})

    _, response = app.test_client.get("/eurc")
    assert response.status == 402
    option = decode_payment_required(response)["accepts"][0]
    assert option["asset"] == EURC
    assert option["amount"] == "500000"
    assert option["extra"]["name"] == "EURC"


def test_asset_with_dynamic_price_rejected(facilitator):
    app = Sanic("CurrencyAppDynamic")
    app.config.TOUCHUP = False
    X402(app, pay_to=PAY_TO, network=TEST_NETWORK, facilitator=facilitator)

    @app.get("/bad")
    @paid(lambda ctx: "$1", asset=EURC)
    async def bad(request):
        return json({"ok": True})

    with pytest.raises(Exception):
        app.test_client.get("/bad")
