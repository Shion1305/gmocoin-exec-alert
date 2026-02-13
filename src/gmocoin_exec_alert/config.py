from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


def _getenv_required(name: str) -> str:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _getenv_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as e:
        raise RuntimeError(f"Invalid int env var {name}={raw!r}") from e


def _getenv_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Invalid bool env var {name}={raw!r}")


@dataclass(frozen=True)
class Config:
    gmocoin_api_key: str
    gmocoin_api_secret: str
    gmocoin_private_api_base: str
    gmocoin_private_ws_base: str

    pagerduty_routing_key: str
    pagerduty_events_api_url: str
    pagerduty_source: str
    pagerduty_severity: str
    pagerduty_dry_run: bool

    alert_channels: tuple[str, ...]

    http_timeout_sec: int
    ws_auth_extend_interval_sec: int
    reconnect_backoff_base_sec: int
    reconnect_backoff_max_sec: int

    dedup_ttl_sec: int
    dedup_max_keys: int

    log_level: str

    # Process monitoring settings
    process_monitor_enabled: bool
    process_monitor_pattern: str
    process_monitor_check_interval_sec: int
    process_monitor_idle_threshold_sec: int


def load_config() -> Config:
    # Load .env if present, but allow env vars to override.
    load_dotenv(override=False)

    # Default to executions only (actual fills).
    alert_channels_raw = os.getenv("ALERT_CHANNELS", "executionEvents")
    channels = tuple(x.strip() for x in alert_channels_raw.split(",") if x.strip())
    if not channels:
        raise RuntimeError("ALERT_CHANNELS is empty")

    return Config(
        gmocoin_api_key=_getenv_required("GMOCOIN_API_KEY"),
        gmocoin_api_secret=_getenv_required("GMOCOIN_API_SECRET"),
        gmocoin_private_api_base=os.getenv(
            "GMOCOIN_PRIVATE_API_BASE", "https://api.coin.z.com/private"
        ).rstrip("/"),
        gmocoin_private_ws_base=os.getenv(
            "GMOCOIN_PRIVATE_WS_BASE", "wss://api.coin.z.com/ws/private/v1/"
        ).rstrip("/")
        + "/",
        pagerduty_routing_key=_getenv_required("PAGERDUTY_ROUTING_KEY"),
        pagerduty_events_api_url=os.getenv(
            "PAGERDUTY_EVENTS_API_URL", "https://events.pagerduty.com/v2/enqueue"
        ).rstrip("/"),
        pagerduty_source=os.getenv("PAGERDUTY_SOURCE", "gmocoin-exec-alert"),
        pagerduty_severity=os.getenv("PAGERDUTY_SEVERITY", "critical"),
        pagerduty_dry_run=_getenv_bool("PAGERDUTY_DRY_RUN", False),
        alert_channels=channels,
        http_timeout_sec=_getenv_int("HTTP_TIMEOUT_SEC", 10),
        ws_auth_extend_interval_sec=_getenv_int("WS_AUTH_EXTEND_INTERVAL_SEC", 3000),
        reconnect_backoff_base_sec=_getenv_int("RECONNECT_BACKOFF_BASE_SEC", 1),
        reconnect_backoff_max_sec=_getenv_int("RECONNECT_BACKOFF_MAX_SEC", 30),
        dedup_ttl_sec=_getenv_int("DEDUP_TTL_SEC", 300),
        dedup_max_keys=_getenv_int("DEDUP_MAX_KEYS", 5000),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        # Process monitoring
        process_monitor_enabled=_getenv_bool("PROCESS_MONITOR_ENABLED", False),
        process_monitor_pattern=os.getenv("PROCESS_MONITOR_PATTERN", r"uv run atc"),
        process_monitor_check_interval_sec=_getenv_int("PROCESS_MONITOR_CHECK_INTERVAL_SEC", 5),
        process_monitor_idle_threshold_sec=_getenv_int("PROCESS_MONITOR_IDLE_THRESHOLD_SEC", 60),
    )
