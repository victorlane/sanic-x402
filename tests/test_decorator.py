from __future__ import annotations

import pytest
from x402.http import PaymentOption, RouteConfig

from sanic_x402.decorator import X402_MARKER, find_marker, normalize_marker, paid


def test_paid_requires_price_or_accepts():
    with pytest.raises(ValueError):
        paid()


def test_paid_marks_handler():
    @paid("$0.10", network="eip155:8453")
    async def handler(request):
        pass

    marker = getattr(handler, X402_MARKER)
    assert marker["price"] == "$0.10"
    assert marker["network"] == "eip155:8453"


def test_normalize_marker_variants():
    assert normalize_marker(None) is None
    assert normalize_marker("$0.01") == {"price": "$0.01"}
    assert normalize_marker({"price": 1}) == {"price": 1}

    option = PaymentOption(
        scheme="exact", pay_to="0xabc", price="$1", network="eip155:8453"
    )
    assert normalize_marker(option) == {"accepts": [option]}

    config = RouteConfig(accepts=[option])
    assert normalize_marker(config) is config


def test_find_marker_traverses_wrapped_handlers():
    from functools import wraps

    class FakeCtx:
        x402 = None

    @paid("$0.01")
    async def handler(request):
        pass

    def other_decorator(fn):
        @wraps(fn)
        async def wrapper(request):
            return await fn(request)

        return wrapper

    wrapped = other_decorator(handler)

    class FakeRoute:
        ctx = FakeCtx()
        handler = wrapped

    marker = find_marker(FakeRoute())
    assert marker is not None
    assert marker["price"] == "$0.01"
