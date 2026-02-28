from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

import websockets

from .config import load_config
from .dedup import DedupCache
from .gmo import GmoCoinPrivateClient
from .pagerduty import PagerDutyClient
from .process_monitor import ProcessMonitor


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _dedup_key_for_event(event: dict[str, Any]) -> str:
    ch = str(event.get("channel", ""))
    if ch == "executionEvents":
        return f"gmocoin:{ch}:{event.get('orderId')}:{event.get('executionId')}"
    if ch == "orderEvents":
        return (
            f"gmocoin:{ch}:{event.get('orderId')}:{event.get('orderStatus')}:"
            f"{event.get('msgType')}:{event.get('orderTimestamp')}"
        )
    return f"gmocoin:{ch}:{hash(json.dumps(event, sort_keys=True, separators=(',', ':')))}"


def _summary_for_event(event: dict[str, Any]) -> str:
    ch = event.get("channel")
    symbol = event.get("symbol", "?")
    side = event.get("side", "?")
    if ch == "executionEvents":
        return (
            f"GMO Coin execution {symbol} {side} "
            f"orderId={event.get('orderId')} executionId={event.get('executionId')} "
            f"price={event.get('executionPrice')} size={event.get('executionSize')}"
        )
    if ch == "orderEvents":
        return (
            f"GMO Coin order {symbol} {side} "
            f"orderId={event.get('orderId')} status={event.get('orderStatus')} "
            f"price={event.get('orderPrice')} size={event.get('orderSize')}"
        )
    return f"GMO Coin {ch} event"


async def _extend_token_loop(
    *,
    stop: asyncio.Event,
    gmo: GmoCoinPrivateClient,
    token: str,
    every_sec: int,
    logger: logging.Logger,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=every_sec)
            return
        except TimeoutError:
            pass

        try:
            await gmo.extend_ws_token(token)
            logger.info("extended ws token")
        except Exception:
            logger.exception("failed to extend ws token (continuing)")


async def _recv_loop(
    *,
    stop: asyncio.Event,
    ws: websockets.WebSocketClientProtocol,
    channels: set[str],
    dedup: DedupCache,
    pd: PagerDutyClient,
    logger: logging.Logger,
) -> None:
    async for raw in ws:
        if stop.is_set():
            return
        try:
            event = json.loads(raw)
        except Exception:
            logger.warning("non-json ws message: %r", raw)
            continue

        if not isinstance(event, dict):
            logger.warning("unexpected ws message type: %r", event)
            continue

        ch = event.get("channel")
        if ch not in channels:
            continue

        key = _dedup_key_for_event(event)
        if dedup.seen_recently(key):
            continue

        summary = _summary_for_event(event)
        try:
            await pd.trigger(dedup_key=key, summary=summary, custom_details=event)
            logger.info("pagerduty triggered: %s", summary)
        except Exception:
            logger.exception("pagerduty trigger failed (continuing): %s", summary)


async def _run_once(stop: asyncio.Event) -> None:
    cfg = load_config()
    _setup_logging(cfg.log_level)
    logger = logging.getLogger("gmocoin-exec-alert")

    gmo = GmoCoinPrivateClient(
        api_key=cfg.gmocoin_api_key,
        api_secret=cfg.gmocoin_api_secret,
        base_url=cfg.gmocoin_private_api_base,
        timeout_sec=cfg.http_timeout_sec,
    )
    pd = PagerDutyClient(
        routing_key=cfg.pagerduty_routing_key,
        events_api_url=cfg.pagerduty_events_api_url,
        source=cfg.pagerduty_source,
        severity=cfg.pagerduty_severity,
        dry_run=cfg.pagerduty_dry_run,
        timeout_sec=cfg.http_timeout_sec,
    )
    dedup = DedupCache(ttl_sec=cfg.dedup_ttl_sec, max_keys=cfg.dedup_max_keys)

    # Create process monitor if enabled
    process_monitor = None
    if cfg.process_monitor_enabled:
        process_monitor = ProcessMonitor(
            pattern=cfg.process_monitor_pattern,
            check_interval_sec=cfg.process_monitor_check_interval_sec,
            idle_threshold_sec=cfg.process_monitor_idle_threshold_sec,
            severity=cfg.process_monitor_severity,
            logger=logger,
        )

    token: str | None = None
    try:
        token = await gmo.create_ws_token()
        ws_url = f"{cfg.gmocoin_private_ws_base}{token}"
        logger.info("connecting private ws: %s***", cfg.gmocoin_private_ws_base)

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            for ch in cfg.alert_channels:
                await ws.send(json.dumps({"command": "subscribe", "channel": ch}))
                logger.info("subscribed: %s", ch)

            tasks = []

            # GMO Coin WebSocket tasks
            extend_task = asyncio.create_task(
                _extend_token_loop(
                    stop=stop,
                    gmo=gmo,
                    token=token,
                    every_sec=cfg.ws_auth_extend_interval_sec,
                    logger=logger,
                )
            )
            recv_task = asyncio.create_task(
                _recv_loop(
                    stop=stop,
                    ws=ws,
                    channels=set(cfg.alert_channels),
                    dedup=dedup,
                    pd=pd,
                    logger=logger,
                )
            )
            tasks.extend([extend_task, recv_task])

            # Process monitor task (if enabled)
            if process_monitor:
                monitor_task = asyncio.create_task(process_monitor.monitor_loop(stop=stop, pd=pd))
                tasks.append(monitor_task)

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in done:
                t.result()
    finally:
        if token:
            try:
                await gmo.delete_ws_token(token)
            except Exception:
                # Not critical; token expires anyway.
                pass
        await pd.aclose()
        await gmo.aclose()


async def _runner() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    cfg = load_config()
    _setup_logging(cfg.log_level)
    logger = logging.getLogger("gmocoin-exec-alert")

    backoff = cfg.reconnect_backoff_base_sec
    while not stop.is_set():
        try:
            await _run_once(stop)
            backoff = cfg.reconnect_backoff_base_sec
        except Exception:
            logger.exception("run failed; reconnecting in %ss", backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, cfg.reconnect_backoff_max_sec)
    return 0


def main() -> int:
    return asyncio.run(_runner())


if __name__ == "__main__":
    raise SystemExit(main())
