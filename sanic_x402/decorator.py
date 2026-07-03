from __future__ import annotations

from typing import Any, Callable

from x402.http import PaymentOption, RouteConfig

X402_MARKER = "__x402_config__"


def paid(
    price: Any = None,
    *,
    pay_to: Any = None,
    network: str | None = None,
    scheme: str | None = None,
    accepts: list[PaymentOption] | PaymentOption | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    resource: str | None = None,
    max_timeout_seconds: int | None = None,
    extra: dict[str, Any] | None = None,
    custom_paywall_html: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> Callable:
    """Mark a route handler as payment-gated via the x402 protocol.

    Apply *under* the route decorator::

        @app.get("/premium")
        @paid("$0.01")
        async def premium(request): ...

    Unset options (``pay_to``, ``network``, ``scheme``) fall back to the
    defaults configured on the app's :class:`~sanic_x402.X402` instance.

    Args:
        price: Money string (``"$0.01"``), number, or an x402 ``AssetAmount``.
            May also be a callable ``(HTTPRequestContext) -> Price`` for
            dynamic pricing. Required unless ``accepts`` is given.
        pay_to: Receiving address; defaults to the app-level ``pay_to``.
        network: CAIP-2 network id (e.g. ``"eip155:8453"`` for Base).
        scheme: Payment scheme, default ``"exact"``.
        accepts: Full list of :class:`x402.http.PaymentOption` for advanced
            multi-network/multi-asset configuration; overrides ``price`` et al.
        description: Human-readable description shown to payers. Defaults to
            the first line of the handler's docstring.
        mime_type: MIME type of the paid resource.
        resource: Explicit resource URL; defaults to the request URL.
        max_timeout_seconds: Max time the payer has to complete payment.
        extra: Scheme-specific extra data for the payment option.
        custom_paywall_html: Custom HTML paywall served to browsers.
        extensions: x402 protocol extensions declared for this route.
    """
    if price is None and accepts is None:
        raise ValueError("paid() requires a price or an explicit accepts=[...]")

    if isinstance(accepts, PaymentOption):
        accepts = [accepts]

    marker: dict[str, Any] = {
        "price": price,
        "pay_to": pay_to,
        "network": network,
        "scheme": scheme,
        "accepts": accepts,
        "description": description,
        "mime_type": mime_type,
        "resource": resource,
        "max_timeout_seconds": max_timeout_seconds,
        "extra": extra,
        "custom_paywall_html": custom_paywall_html,
        "extensions": extensions,
    }

    def decorate(handler: Callable) -> Callable:
        setattr(handler, X402_MARKER, marker)
        return handler

    return decorate


def normalize_marker(value: Any) -> dict[str, Any] | RouteConfig | None:
    """Coerce the supported per-route config spellings into a marker.

    Accepts a marker dict (from ``@paid``), a bare price (``ctx_x402="$0.01"``),
    a :class:`PaymentOption`, or a full :class:`RouteConfig`.
    """
    if value is None:
        return None
    if isinstance(value, RouteConfig):
        return value
    if isinstance(value, PaymentOption):
        return {"accepts": [value]}
    if isinstance(value, dict):
        return value
    # Bare price: string, number, AssetAmount, or dynamic-price callable.
    return {"price": value}


def find_marker(route: Any) -> dict[str, Any] | RouteConfig | None:
    """Find x402 config for a route: ``ctx_x402=`` kwarg or ``@paid`` marker."""
    ctx_value = getattr(route.ctx, "x402", None)
    if ctx_value is not None:
        return normalize_marker(ctx_value)

    handler = route.handler
    while handler is not None:
        marker = getattr(handler, X402_MARKER, None)
        if marker is not None:
            return marker
        handler = getattr(handler, "__wrapped__", None)
    return None
