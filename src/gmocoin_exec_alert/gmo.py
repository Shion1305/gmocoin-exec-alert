from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx


class GmoCoinPrivateClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str,
        timeout_sec: int,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_sec)
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_ws_token(self) -> str:
        # Spec: POST /private/v1/ws-auth with signed headers.
        resp = await self._request_signed(
            method="POST",
            path="/v1/ws-auth",
            body={},
            include_body_in_sign=True,
        )
        data = resp.get("data")
        if not isinstance(data, str) or not data:
            raise RuntimeError(f"Unexpected ws-auth response: {resp!r}")
        return data

    async def extend_ws_token(self, token: str) -> None:
        # Spec examples sign with timestamp + method + path (no body in sign).
        await self._request_signed(
            method="PUT",
            path="/v1/ws-auth",
            body={"token": token},
            include_body_in_sign=False,
        )

    async def delete_ws_token(self, token: str) -> None:
        await self._request_signed(
            method="DELETE",
            path="/v1/ws-auth",
            body={"token": token},
            include_body_in_sign=False,
        )

    async def _request_signed(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        include_body_in_sign: bool,
    ) -> Any:
        timestamp = str(int(time.time() * 1000))
        body_str = "" if body is None else json.dumps(body, separators=(",", ":"))

        text = timestamp + method.upper() + path
        if include_body_in_sign:
            text += body_str

        sign = hmac.new(
            self._api_secret.encode("utf-8"),
            text.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "API-KEY": self._api_key,
            "API-TIMESTAMP": timestamp,
            "API-SIGN": sign,
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}{path}"
        resp = await self._client.request(method, url, headers=headers, content=body_str)
        if resp.status_code // 100 != 2:
            raise RuntimeError(
                f"GMO Coin API error: {method} {path} -> {resp.status_code} {resp.text}"
            )

        # Some endpoints may return empty body; ws-auth create returns JSON.
        if not resp.content:
            return None
        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Non-JSON GMO Coin response: {resp.text}") from e

        # GMO Coin APIs commonly return HTTP 200 with non-zero status on application errors.
        if isinstance(data, dict) and data.get("status") not in (None, 0):
            raise RuntimeError(f"GMO Coin API status error: {method} {path} -> {data!r}")
        return data
