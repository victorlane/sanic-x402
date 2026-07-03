from __future__ import annotations

from sanic.exceptions import SanicException


class PaymentRequired(SanicException):
    """HTTP 402 Payment Required.

    Raise from a handler to reject a request that has not paid. Prefer the
    ``@paid`` decorator for protocol-compliant x402 gating; this exception is
    a low-level primitive for manual flows.
    """

    status_code = 402
    quiet = True
