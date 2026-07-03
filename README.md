# sanic-x402

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![x402 Protocol](https://img.shields.io/badge/protocol-x402-black.svg)](https://www.x402.org/)

Payment-gated routes for [Sanic](https://sanic.dev). Charge stablecoin micropayments for any endpoint with a single decorator, powered by the [x402 protocol](https://www.x402.org/).

```python
@app.get("/premium")
@paid("$0.01")
async def premium(request):
    return json({"data": "..."})
```

## Why sanic-x402?

- **One decorator to monetize an endpoint**: no accounts, no API keys, no payment processor. Clients pay per request over HTTP 402.
- **Built on the official x402 SDK**: speaks both x402 v1 (`X-PAYMENT`) and v2 (`PAYMENT-SIGNATURE`) wire formats, works with any facilitator, and serves the built-in HTML paywall to browsers.
- **Safe by default**: payments settle only after your handler succeeds. Failed responses are never charged.
- **AI-agent ready**: agents holding a funded wallet can discover the price from the 402 challenge and pay autonomously.
- **Stays out of your way**: plain Sanic middleware and decorators, no base classes, no app rewrites.

## Feature Overview

| Feature | Description |
| ------- | ----------- |
| `@paid` decorator | Gate a route with a price string like `"$0.01"` |
| Route kwarg | Gate via `ctx_x402="$0.05"` without importing anything |
| Path patterns | Gate whole subtrees, like the official Express/FastAPI middlewares |
| Dynamic pricing | Compute price or receiver per request with a callable |
| Multi-network | Offer several payment options (EVM, Solana, and more) per route |
| Browser paywall | Human visitors get a hosted payment page, agents get JSON |
| Settlement receipts | Successful responses carry a `PAYMENT-RESPONSE` header |
| sanic-ext support | Optional config-driven setup for sanic-ext users |

## Quick Start

Install the package (the EVM extra covers the default Base/USDC setup):

```bash
pip install sanic-x402[evm]
```

Attach it to your app and mark a route as paid:

```python
from sanic import Sanic
from sanic.response import json
from sanic_x402 import X402, paid

app = Sanic("Api")
X402(app, pay_to="0xYourReceivingAddress")  # Base Sepolia testnet by default

@app.get("/free")
async def free(request):
    return json({"hello": "world"})

@app.get("/premium")
@paid("$0.01")
async def premium(request):
    """Premium market data."""
    return json({"data": "..."})
```

Unpaid requests to `/premium` receive `402 Payment Required` with a signed challenge. Paid requests are verified with the facilitator, your handler runs, and the payment settles on-chain. The settlement receipt is returned in the `PAYMENT-RESPONSE` header.

Going to production on Base mainnet:

```python
X402(
    app,
    pay_to="0xYourReceivingAddress",
    network="eip155:8453",
    facilitator="https://your-facilitator.example",  # e.g. Coinbase CDP
)
```

The default facilitator is the testnet facilitator at `https://x402.org/facilitator`. It is an API base URL, not a web page: the bare path returns 404, while `GET /facilitator/supported` lists its capabilities.

## Three Ways to Gate a Route

**The `@paid` decorator** (recommended). Apply it under the route decorator:

```python
@app.get("/reports/<report_id>")
@paid("$0.25", description="Full analyst report", mime_type="application/json")
async def report(request, report_id):
    ...
```

**A route kwarg.** No extra import needed:

```python
@app.get("/premium", ctx_x402="$0.05")
async def premium(request):
    ...
```

`ctx_x402` accepts a bare price, a dict of `@paid` kwargs, an x402 `PaymentOption`, or a full `RouteConfig`.

**Path patterns.** Gate whole subtrees, like the official Express and FastAPI middlewares:

```python
from sanic_x402 import X402, RouteConfig, PaymentOption

X402(app, routes={
    "GET /api/premium/*": RouteConfig(accepts=[
        PaymentOption(scheme="exact", pay_to="0x...", price="$0.10",
                      network="eip155:8453"),
    ]),
})
```

## Supported Currencies

x402 is asset-agnostic: a payment option names any token on any supported network, and sanic-x402 exposes all of it.

**USD money strings** like `"$0.01"` are the simple path. They resolve to the network's default USD stablecoin from the SDK registry, which covers USDC on Base, Base Sepolia, Polygon, Arbitrum One, Arbitrum Sepolia, Monad, XDC and others, plus USDT0 (Stable), MegaUSD (MegaETH), Mezo USD, and more.

**Any other token** (EURC, DAI, or your own ERC-20/SPL asset) works via `asset=`:

```python
@paid(
    "€0.50",
    asset="0x808456652fdb597867f38412077A9182bf77359F",  # EURC on Base
    asset_decimals=6,
    asset_extra={"name": "EURC", "version": "2"},  # token's EIP-712 domain
)
async def handler(request): ...
```

The price is converted to atomic units with `asset_decimals`, and currency symbols or codes in the string are stripped. For full control, pass an `AssetAmount` directly as the price:

```python
from sanic_x402 import AssetAmount

@paid(AssetAmount(amount="500000", asset="0x8084...", extra={"name": "EURC", "version": "2"}))
```

Two practical constraints apply. On EVM networks with the `exact` scheme, the token must support EIP-3009 `transferWithAuthorization` (USDC and EURC do) or the Permit2 flow. And your facilitator must support the scheme and network pair; check `GET <facilitator>/supported`. The v2 spec also allows ISO 4217 codes (like `"USD"`) as the asset for fiat facilitators.

## Advanced Usage

<details>
<summary><b>Dynamic pricing and receivers</b></summary>

`price` and `pay_to` accept callables that receive the x402 `HTTPRequestContext`:

```python
@paid(lambda ctx: "$1.00" if ctx.adapter.get_query_param("hd") else "$0.10")
```

</details>

<details>
<summary><b>Multiple payment options per route</b></summary>

```python
from sanic_x402 import PaymentOption, paid

@paid(accepts=[
    PaymentOption(scheme="exact", pay_to="0xEvm...", price="$0.01",
                  network="eip155:8453"),
    PaymentOption(scheme="exact", pay_to="Sol...", price="$0.01",
                  network="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"),
])
async def handler(request): ...
```

Non-EVM schemes must be registered explicitly:

```python
from x402.mechanisms.svm.exact import ExactSvmServerScheme

X402(app, pay_to="...", schemes=[
    ("eip155:*", ExactEvmServerScheme()),
    ("solana:*", ExactSvmServerScheme()),
])
```

</details>

<details>
<summary><b>Payment info in handlers</b></summary>

After verification, `request.ctx.x402` holds a `PaymentInfo` with the decoded `payload` and matched `requirements`:

```python
@app.get("/premium")
@paid("$0.01")
async def premium(request):
    payment = request.ctx.x402
    return json({"paid_on": payment.requirements.network})
```

</details>

<details>
<summary><b>Paywall customization</b></summary>

```python
from sanic_x402 import PaywallConfig

X402(app, pay_to="...", paywall=PaywallConfig(app_name="My API", testnet=True))
```

</details>

<details>
<summary><b>sanic-ext integration</b></summary>

Install with `pip install sanic-x402[ext]`, then configure everything through app config:

```python
from sanic_ext import Extend
from sanic_x402.ext import X402Extension

app.config.X402_PAY_TO = "0xYourAddress"
app.config.X402_NETWORK = "eip155:8453"
app.extend(extensions=[X402Extension])
```

</details>

## How It Works

1. A client requests a gated route without payment.
2. sanic-x402 responds `402` with a challenge (JSON for agents, an HTML paywall for browsers) describing price, asset, network, and receiver.
3. The client signs a payment authorization and retries with a `PAYMENT-SIGNATURE` header.
4. The payment is verified with the facilitator, then your handler runs.
5. On a successful response the payment settles on-chain and the receipt is attached as a `PAYMENT-RESPONSE` header.

## Semantics and Caveats

- **No charge on failure.** If the handler raises or returns a 4xx/5xx, settlement is skipped and the payment authorization expires unspent.
- **Settlement runs after the handler**, in response middleware. If settlement fails, the client receives `402` with the failure receipt instead of being charged for the body.
- **Streaming.** Responses returned from the handler (including `ResponseStream`) settle before the body is sent. Mid-handler `await request.respond()` triggers settlement at `respond()` time, so prefer returned responses on paid routes.
- **Websockets are not gated.** A warning is logged if `@paid` is applied to one.
- **Facilitator sync is lazy.** Capabilities are fetched on the first protected request; pass `sync_facilitator_on_start=False` to disable.

## Development

```bash
uv sync
uv run pytest
```

Tests run fully offline against a fake facilitator.

## Resources

- [x402 protocol](https://www.x402.org/)
- [x402 documentation](https://docs.x402.org/)
- [x402 specification](https://github.com/x402-foundation/x402/tree/main/specs)
- [x402 Python SDK](https://pypi.org/project/x402/)
- [Sanic documentation](https://sanic.dev)

## License

MIT. See [LICENSE](LICENSE).
