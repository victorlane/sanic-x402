from __future__ import annotations

from typing import Any

from sanic.request import Request


class SanicHTTPAdapter:
    """x402 ``HTTPAdapter`` implementation over a Sanic :class:`Request`."""

    def __init__(self, request: Request) -> None:
        self._request = request

    def get_header(self, name: str) -> str | None:
        return self._request.headers.get(name)

    def get_method(self) -> str:
        return self._request.method

    def get_path(self) -> str:
        return self._request.path

    def get_url(self) -> str:
        return self._request.url

    def get_accept_header(self) -> str:
        return self._request.headers.get("accept", "")

    def get_user_agent(self) -> str:
        return self._request.headers.get("user-agent", "")

    def get_query_params(self) -> dict[str, str | list[str]]:
        # Sanic's request.args maps each key to a list; collapse singletons.
        return {
            key: values[0] if len(values) == 1 else list(values)
            for key, values in self._request.args.items()
        }

    def get_query_param(self, name: str) -> str | None:
        return self._request.args.get(name)

    def get_body(self) -> Any:
        try:
            return self._request.json
        except Exception:
            return None
