from __future__ import annotations

import pytest

pytest.importorskip("sanic_ext")

from sanic import Sanic
from sanic.response import json

from sanic_x402 import paid

from .conftest import PAY_TO, TEST_NETWORK, decode_payment_required


def test_extension_gates_routes_from_config(facilitator, monkeypatch):
    from sanic_x402.ext import X402Extension

    app = Sanic("ExtApp")
    app.config.TOUCHUP = False
    app.config.X402_PAY_TO = PAY_TO
    app.config.X402_NETWORK = TEST_NETWORK
    app.extend(extensions=[X402Extension], built_in_extensions=False)

    # The extension has no config hook for a client object, so inject the
    # offline fake facilitator directly.
    app.ctx.x402.facilitator = facilitator

    @app.get("/premium")
    @paid("$0.02")
    async def premium(request):
        return json({"ok": True})

    _, response = app.test_client.get("/premium")
    assert response.status == 402
    challenge = decode_payment_required(response)
    assert challenge["accepts"][0]["payTo"] == PAY_TO
    assert challenge["accepts"][0]["network"] == TEST_NETWORK
