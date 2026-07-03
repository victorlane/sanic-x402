from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sanic import Sanic
from sanic.log import logger
from sanic.request import Request
from sanic.response import HTTPResponse, html
from sanic.response import json as json_response
from x402 import x402ResourceServer
from x402.http import (
    HTTPFacilitatorClient,
    HTTPRequestContext,
    HTTPResponseInstructions,
    PaymentOption,
    PaywallConfig,
    RouteConfig,
    RouteConfigurationError,
    RoutesConfig,
)
from x402.http.types import HTTPTransportContext
from x402.http.constants import SETTLEMENT_OVERRIDES_HEADER
from x402.http.facilitator_client_base import FacilitatorResponseError
from x402.http.x402_http_server import PaywallProvider, x402HTTPResourceServer
from x402.schemas import AssetAmount, VerifiedPaymentCancelOptions

from .adapter import SanicHTTPAdapter
from .decorator import find_marker

DEFAULT_NETWORK = "eip155:84532"  # Base Sepolia testnet
DEFAULT_SCHEME = "exact"

_RESULT_NO_PAYMENT = "no-payment-required"
_RESULT_ERROR = "payment-error"
_RESULT_VERIFIED = "payment-verified"


@dataclass
class PaymentInfo:
    """Verified payment details, available to handlers as ``request.ctx.x402``."""

    payload: Any
    requirements: Any


@dataclass
class _GateState:
    gate: x402HTTPResourceServer
    result: Any
    context: HTTPRequestContext


def _to_asset_amount(
    price: Any, asset: str, decimals: int, extra: dict[str, Any] | None
) -> AssetAmount:
    """Convert a decimal price in a custom asset to atomic units.

    Accepts numbers and strings with optional currency decoration, e.g.
    ``"€0.50"``, ``"0.50 EURC"``, ``0.5``, ``Decimal("0.5")``.
    """
    if isinstance(price, AssetAmount):
        return price
    if isinstance(price, str):
        cleaned = price.strip().lstrip("$€£¥")
        cleaned = re.sub(r"\s*[A-Za-z][A-Za-z0-9.]*\s*$", "", cleaned).strip()
    else:
        cleaned = str(price)
    atomic = int(Decimal(cleaned) * (Decimal(10) ** decimals))
    return AssetAmount(amount=str(atomic), asset=asset, extra=extra or {})


def _facilitator_error(error: FacilitatorResponseError) -> HTTPResponse:
    return json_response({"error": str(error)}, status=502)


def _response_from_instructions(
    instructions: HTTPResponseInstructions | None,
) -> HTTPResponse:
    if instructions is None:
        return json_response({"error": "Payment required"}, status=402)
    headers = dict(instructions.headers or {})
    if instructions.is_html:
        return html(
            instructions.body or "", status=instructions.status, headers=headers
        )
    return json_response(
        instructions.body if instructions.body is not None else {},
        status=instructions.status,
        headers=headers,
    )


class X402:
    """Payment-gate Sanic routes with the x402 protocol.

    Usage::

        from sanic import Sanic
        from sanic_x402 import X402, paid

        app = Sanic("Api")
        X402(app, pay_to="0xYourAddress", network="eip155:8453")

        @app.get("/premium")
        @paid("$0.01", description="Premium data")
        async def premium(request):
            return json({"data": "..."})

    Routes may also be gated without the decorator, via a route kwarg
    (``@app.get("/premium", ctx_x402="$0.01")``) or app-wide path patterns
    (``X402(app, routes={"GET /api/*": ...})`` using x402 ``RouteConfig``).
    """

    def __init__(
        self,
        app: Sanic | None = None,
        *,
        pay_to: Any = None,
        network: str = DEFAULT_NETWORK,
        scheme: str = DEFAULT_SCHEME,
        facilitator: Any = None,
        routes: RoutesConfig | None = None,
        schemes: list[tuple[str, Any]] | None = None,
        paywall: PaywallConfig | None = None,
        paywall_provider: PaywallProvider | None = None,
        sync_facilitator_on_start: bool = True,
        default_max_timeout_seconds: int | None = None,
    ) -> None:
        """
        Args:
            app: Sanic app to attach to (or call :meth:`init_app` later).
            pay_to: Default receiving address for all paid routes.
            network: Default CAIP-2 network (default: Base Sepolia testnet
                ``eip155:84532``; use ``eip155:8453`` for Base mainnet).
            scheme: Default payment scheme (``"exact"``).
            facilitator: Facilitator URL string, an x402 facilitator client,
                or a list of clients. Defaults to ``https://x402.org/facilitator``.
            routes: Optional pattern-based x402 route config applied in
                addition to decorated routes (``{"GET /api/*": RouteConfig}``).
            schemes: Override scheme registration as ``[(network_pattern,
                scheme_server), ...]``. Defaults to the EVM ``exact`` scheme
                on ``eip155:*``.
            paywall: Paywall UI customization for browser clients.
            paywall_provider: Custom paywall HTML provider.
            sync_facilitator_on_start: Fetch facilitator capabilities and
                validate route config on the first protected request.
            default_max_timeout_seconds: Default payment timeout per option.
        """
        self.pay_to = pay_to
        self.network = network
        self.scheme = scheme
        self.facilitator = facilitator
        self.paywall = paywall
        self.paywall_provider = paywall_provider
        self.sync_facilitator_on_start = sync_facilitator_on_start
        self.default_max_timeout_seconds = default_max_timeout_seconds

        self._routes = routes
        self._schemes = schemes
        self._core: x402ResourceServer | None = None
        self._gates: dict[str, x402HTTPResourceServer] = {}
        self._pattern_gate: x402HTTPResourceServer | None = None
        self._initialized = False
        self._init_lock: asyncio.Lock | None = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app: Sanic) -> X402:
        app.ctx.x402 = self
        app.before_server_start(self._setup)
        app.on_request(self._on_request)
        app.on_response(self._on_response)
        return self

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _build_core(self) -> x402ResourceServer:
        facilitator = self.facilitator
        if facilitator is None:
            clients: list[Any] = [HTTPFacilitatorClient()]
        elif isinstance(facilitator, str):
            clients = [HTTPFacilitatorClient({"url": facilitator})]
        elif isinstance(facilitator, (list, tuple)):
            clients = [
                HTTPFacilitatorClient({"url": item}) if isinstance(item, str) else item
                for item in facilitator
            ]
        else:
            clients = [facilitator]

        server = x402ResourceServer(clients)

        if self._schemes is None:
            try:
                from x402.mechanisms.evm.exact import register_exact_evm_server
            except ImportError as error:
                raise ImportError(
                    "The default EVM 'exact' scheme needs the x402 EVM extra: "
                    "pip install sanic-x402[evm], or pass schemes=[...] to "
                    "X402() explicitly."
                ) from error
            register_exact_evm_server(server)
        else:
            for network_pattern, scheme_server in self._schemes:
                server.register(network_pattern, scheme_server)
        return server

    def _build_route_config(self, marker: Any, route: Any) -> RouteConfig:
        if isinstance(marker, RouteConfig):
            return marker

        accepts = marker.get("accepts")
        if accepts is None:
            pay_to = marker.get("pay_to") or self.pay_to
            if pay_to is None:
                raise RuntimeError(
                    f"Route '{route.name}' is marked @paid but has no pay_to "
                    "address: pass pay_to= to @paid() or set a default on X402()."
                )
            price = marker["price"]
            asset = marker.get("asset")
            if asset is not None:
                if callable(price):
                    raise ValueError(
                        f"Route '{route.name}': asset= cannot be combined with "
                        "a dynamic price callable; return an AssetAmount from "
                        "the callable instead."
                    )
                price = _to_asset_amount(
                    price,
                    asset,
                    marker.get("asset_decimals") or 6,
                    marker.get("asset_extra"),
                )
            accepts = [
                PaymentOption(
                    scheme=marker.get("scheme") or self.scheme,
                    pay_to=pay_to,
                    price=price,
                    network=marker.get("network") or self.network,
                    max_timeout_seconds=marker.get("max_timeout_seconds")
                    or self.default_max_timeout_seconds,
                    extra=marker.get("extra"),
                )
            ]

        description = marker.get("description")
        if description is None:
            doc = getattr(route.handler, "__doc__", None)
            description = doc.strip().splitlines()[0] if doc else None

        return RouteConfig(
            accepts=accepts,
            resource=marker.get("resource"),
            description=description,
            mime_type=marker.get("mime_type"),
            custom_paywall_html=marker.get("custom_paywall_html"),
            extensions=marker.get("extensions"),
        )

    async def _setup(self, app: Sanic) -> None:
        # Runs once per server (re)start in each worker: build a fresh core
        # and reset the lazy-initialization state that belongs to it.
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._gates = {}
        core = self._core = self._build_core()

        for route in app.router.routes:
            marker = find_marker(route)
            if marker is None:
                continue
            if getattr(route.ctx, "websocket", False) or getattr(
                route.extra, "websocket", False
            ):
                logger.warning(
                    "sanic-x402: ignoring @paid on websocket route '%s' "
                    "(x402 gating requires HTTP request/response)",
                    route.name,
                )
                continue
            gate = x402HTTPResourceServer(core, self._build_route_config(marker, route))
            if self.paywall_provider is not None:
                gate.register_paywall_provider(self.paywall_provider)
            self._gates[route.name] = gate

        if self._routes is not None:
            self._pattern_gate = x402HTTPResourceServer(core, self._routes)
            if self.paywall_provider is not None:
                self._pattern_gate.register_paywall_provider(self.paywall_provider)

        if not self._gates and self._pattern_gate is None:
            logger.info("sanic-x402: attached, but no routes are payment-gated")

    # ------------------------------------------------------------------
    # Request/response middleware
    # ------------------------------------------------------------------

    def _make_context(self, request: Request) -> HTTPRequestContext:
        adapter = SanicHTTPAdapter(request)
        return HTTPRequestContext(
            adapter=adapter,
            path=request.path,
            method=request.method,
            payment_header=(
                adapter.get_header("payment-signature")
                or adapter.get_header("x-payment")
            ),
        )

    async def _ensure_initialized(self) -> None:
        # Fetch facilitator capabilities once, then validate every gate's
        # route config against them. Mirrors the SDK's own middlewares,
        # including the sync (briefly blocking) facilitator fetch.
        assert self._init_lock is not None
        async with self._init_lock:
            if self._initialized:
                return
            gates = list(self._gates.values())
            if self._pattern_gate is not None:
                gates.append(self._pattern_gate)
            if gates:
                gates[0].initialize()
                for gate in gates[1:]:
                    errors = gate._validate_route_configuration()
                    if errors:
                        raise RouteConfigurationError(errors)
            self._initialized = True

    async def _on_request(self, request: Request) -> HTTPResponse | None:
        route = request.route
        if route is None:
            return None

        context: HTTPRequestContext | None = None
        gate = self._gates.get(route.name)
        if gate is None:
            if self._pattern_gate is None:
                return None
            context = self._make_context(request)
            if not self._pattern_gate.requires_payment(context):
                return None
            gate = self._pattern_gate
        if context is None:
            context = self._make_context(request)

        if self.sync_facilitator_on_start and not self._initialized:
            try:
                await self._ensure_initialized()
            except FacilitatorResponseError as error:
                return _facilitator_error(error)

        try:
            result = await gate.process_http_request(context, self.paywall)
        except FacilitatorResponseError as error:
            return _facilitator_error(error)

        if result.type == _RESULT_NO_PAYMENT:
            return None
        if result.type == _RESULT_ERROR:
            return _response_from_instructions(result.response)

        # Payment verified: let the handler run, settle in response middleware.
        request.ctx.x402 = PaymentInfo(
            payload=result.payment_payload,
            requirements=result.payment_requirements,
        )
        request.ctx._x402_state = _GateState(gate=gate, result=result, context=context)
        return None

    async def _on_response(
        self, request: Request, response: HTTPResponse
    ) -> HTTPResponse | None:
        state: _GateState | None = getattr(request.ctx, "_x402_state", None)
        if state is None:
            return None
        request.ctx._x402_state = None

        result = state.result
        dispatcher = result.cancellation_dispatcher
        status = getattr(response, "status", 500)

        # Don't charge for failed responses.
        if status >= 400:
            if dispatcher is not None:
                await dispatcher.cancel(
                    VerifiedPaymentCancelOptions(
                        reason="handler_failed", response_status=status
                    )
                )
            return None

        headers = dict(response.headers)
        overrides = state.gate._extract_settlement_overrides(headers)
        if overrides is not None:
            headers.pop(SETTLEMENT_OVERRIDES_HEADER, None)
            try:
                del response.headers[SETTLEMENT_OVERRIDES_HEADER]
            except KeyError:
                pass

        transport_context = HTTPTransportContext(
            request=state.context, response_headers=headers
        )

        try:
            settle_result = await state.gate.process_settlement(
                result.payment_payload,
                result.payment_requirements,
                context=state.context,
                settlement_overrides=overrides,
                declared_extensions=result.declared_extensions,
                transport_context=transport_context,
            )
        except FacilitatorResponseError as error:
            return _facilitator_error(error)
        except Exception:
            logger.exception("sanic-x402: settlement failed for %s", request.path)
            return json_response({}, status=402)

        if not settle_result.success:
            return _response_from_instructions(settle_result.response)

        response.headers.update(settle_result.headers)
        return None
