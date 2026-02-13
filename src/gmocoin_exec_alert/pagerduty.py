from __future__ import annotations

from typing import Any

import httpx


class PagerDutyClient:
    def __init__(
        self,
        *,
        routing_key: str,
        events_api_url: str,
        source: str,
        severity: str,
        dry_run: bool,
        timeout_sec: int,
    ) -> None:
        self._routing_key = routing_key
        self._events_api_url = events_api_url
        self._source = source
        self._severity = severity
        self._dry_run = dry_run
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def trigger(
        self,
        *,
        dedup_key: str,
        summary: str,
        custom_details: dict[str, Any],
        component: str | None = None,
        group: str | None = None,
        class_: str | None = None,
    ) -> None:
        if self._dry_run:
            return

        payload: dict[str, Any] = {
            "summary": summary,
            "source": self._source,
            "severity": self._severity,
            "custom_details": custom_details,
        }
        if component:
            payload["component"] = component
        if group:
            payload["group"] = group
        if class_:
            payload["class"] = class_

        body = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": dedup_key,
            "payload": payload,
        }

        resp = await self._client.post(self._events_api_url, json=body)
        if resp.status_code != 202:
            raise RuntimeError(
                f"PagerDuty error: {resp.status_code} {resp.text} (dedup_key={dedup_key})"
            )

    async def resolve(
        self,
        *,
        dedup_key: str,
    ) -> None:
        """Resolve an incident with the given dedup_key."""
        if self._dry_run:
            return

        body = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
        }

        resp = await self._client.post(self._events_api_url, json=body)
        if resp.status_code != 202:
            raise RuntimeError(
                f"PagerDuty resolve error: {resp.status_code} {resp.text} (dedup_key={dedup_key})"
            )

