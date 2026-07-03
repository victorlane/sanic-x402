"""Optional sanic-ext integration.

Lets sanic-ext users enable x402 purely through app config::

    from sanic import Sanic
    from sanic_ext import Extend
    from sanic_x402.ext import X402Extension

    app = Sanic("Api")
    app.config.X402_PAY_TO = "0xYourAddress"
    app.config.X402_NETWORK = "eip155:8453"
    Extend.register(X402Extension)  # or app.extend(extensions=[X402Extension])

Config keys: ``X402_PAY_TO`` (required), ``X402_NETWORK``, ``X402_SCHEME``,
``X402_FACILITATOR`` (URL). Route gating still happens via ``@paid`` /
``ctx_x402``.
"""

from __future__ import annotations

try:
    from sanic_ext.extensions.base import Extension
except ImportError as error:  # pragma: no cover
    raise ImportError(
        "sanic_x402.ext requires sanic-ext; install with: pip install sanic-x402[ext]"
    ) from error

from .extension import DEFAULT_NETWORK, DEFAULT_SCHEME, X402


class X402Extension(Extension):
    # sanic-ext requires purely alphabetic extension names.
    name = "paywall"

    def startup(self, bootstrap) -> None:
        # X402_* keys live on the app config; sanic-ext's own Config only
        # mirrors keys it predefines, so read from self.app.config.
        pay_to = self.app.config.get("X402_PAY_TO")
        if not pay_to:
            return
        X402(
            self.app,
            pay_to=pay_to,
            network=self.app.config.get("X402_NETWORK", DEFAULT_NETWORK),
            scheme=self.app.config.get("X402_SCHEME", DEFAULT_SCHEME),
            facilitator=self.app.config.get("X402_FACILITATOR"),
        )

    def included(self) -> bool:
        return bool(self.app.config.get("X402_PAY_TO"))

    def label(self) -> str:
        network = self.app.config.get("X402_NETWORK", DEFAULT_NETWORK)
        return f"x402 on {network}"
