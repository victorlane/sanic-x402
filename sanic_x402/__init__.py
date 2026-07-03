"""sanic-x402: x402 payment-gated routes for Sanic.

Gate any route behind an on-chain stablecoin payment with one decorator::

    from sanic import Sanic
    from sanic.response import json
    from sanic_x402 import X402, paid

    app = Sanic("Api")
    X402(app, pay_to="0xYourAddress")

    @app.get("/premium")
    @paid("$0.01")
    async def premium(request):
        return json({"report": "..."})

See https://www.x402.org/ for the protocol.
"""

from x402.http import (
    HTTPFacilitatorClient,
    PaymentOption,
    PaywallConfig,
    RouteConfig,
)

from .adapter import SanicHTTPAdapter
from .decorator import paid
from .exceptions import PaymentRequired
from .extension import DEFAULT_NETWORK, DEFAULT_SCHEME, PaymentInfo, X402

__version__ = "0.1.0"

__all__ = [
    "X402",
    "paid",
    "PaymentInfo",
    "PaymentRequired",
    "SanicHTTPAdapter",
    "DEFAULT_NETWORK",
    "DEFAULT_SCHEME",
    # Re-exports from the x402 SDK for convenience
    "PaymentOption",
    "RouteConfig",
    "PaywallConfig",
    "HTTPFacilitatorClient",
]
