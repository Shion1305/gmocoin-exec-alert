# gmocoin-exec-alert

Listens to GMO Coin **Private WebSocket API** execution notifications and triggers PagerDuty alerts.

Also supports monitoring local machine learning processes (e.g., `uv run atc`) and sends PagerDuty notifications when jobs complete.

## Setup

1. Create `.env` (copy from `.env.example`) and fill in:
   - `GMOCOIN_API_KEY`
   - `GMOCOIN_API_SECRET`
   - `PAGERDUTY_ROUTING_KEY`

2. In GMO Coin, ensure the API key has the WebSocket notification permissions enabled (order/execution).

3. Install dependencies with `uv`:

```bash
uv sync
```

## Run

```bash
uv run gmocoin-exec-alert
```

## Process Monitoring (Optional)

To enable monitoring of local ML processes:

1. Set `PROCESS_MONITOR_ENABLED=true` in your `.env`
2. Customize the pattern if needed (default: `uv run atc`)
3. Adjust check interval and idle threshold as needed

The monitor will:
- Watch for processes matching the pattern
- When processes are detected, track them continuously
- Send a PagerDuty alert when all processes are gone for the configured threshold (default: 60 seconds)

Example `.env` configuration:
```bash
PROCESS_MONITOR_ENABLED=true
PROCESS_MONITOR_PATTERN=uv run atc
PROCESS_MONITOR_CHECK_INTERVAL_SEC=5
PROCESS_MONITOR_IDLE_THRESHOLD_SEC=60
```

## Notes

- This uses the GMO Coin `POST /private/v1/ws-auth` endpoint to mint a temporary access token, connects to:
  - `wss://api.coin.z.com/ws/private/v1/{ACCESS_TOKEN}`
- The server pings about once per minute; the client responds automatically.
- By default this subscribes to `executionEvents` only. You can override via `ALERT_CHANNELS`.
- The process monitor uses `ps aux` to find matching processes and works on Unix-like systems (Linux, macOS).
