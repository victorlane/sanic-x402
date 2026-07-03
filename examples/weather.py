"""Minimal sanic-x402 example: a paid weather API on Base Sepolia testnet.

Run:
    pip install sanic-x402[evm]
    python examples/weather.py

Then:
    curl -i http://localhost:8000/weather/amsterdam     # free
    curl -i http://localhost:8000/forecast/amsterdam    # 402 challenge

Pay the challenge with any x402 client (e.g. `pip install x402[httpx,evm]`
and x402HTTPClient with a funded Base Sepolia wallet), or open the forecast
URL in a browser to see the built-in paywall.
"""

from sanic import Sanic
from sanic.response import json

from sanic_x402 import X402, PaywallConfig, paid

PAY_TO = "0x0000000000000000000000000000000000000000"  # your receiving address

app = Sanic("WeatherApi")
X402(
    app,
    pay_to=PAY_TO,
    network="eip155:84532",  # Base Sepolia; use eip155:8453 for Base mainnet
    paywall=PaywallConfig(app_name="Weather API", testnet=True),
)


@app.get("/weather/<city>")
async def weather(request, city: str):
    return json({"city": city, "conditions": "sunny", "temp_c": 21})


@app.get("/forecast/<city>")
@paid("$0.01")
async def forecast(request, city: str):
    """14-day hourly forecast."""
    payment = request.ctx.x402
    return json(
        {
            "city": city,
            "days": 14,
            "forecast": ["sunny"] * 14,
            "paid_on": payment.requirements.network,
        }
    )


if __name__ == "__main__":
    app.run(port=8000, single_process=True)
