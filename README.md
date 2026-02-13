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
- Auto-resolve the PagerDuty incident when processes restart

Example `.env` configuration:
```bash
PROCESS_MONITOR_ENABLED=true
PROCESS_MONITOR_PATTERN=uv run atc
PROCESS_MONITOR_CHECK_INTERVAL_SEC=5
PROCESS_MONITOR_IDLE_THRESHOLD_SEC=60
```

## Kubernetes Deployment

### Prerequisites

- Kubernetes cluster (v1.19+)
- Helm 3
- Docker image pushed to GHCR (automated via GitHub Actions)

### Building and Pushing Docker Image

The Docker image is automatically built and pushed to GitHub Container Registry (GHCR) when you push to the `main` branch or create a tag:

```bash
# Push to main branch (builds :latest)
git push origin main

# Or create a version tag (builds :v1.0.0, :1.0, :1)
git tag v1.0.0
git push origin v1.0.0
```

The image will be available at: `ghcr.io/YOUR_USERNAME/gmocoin-exec-alert`

### Deploy with Helm

1. **Prepare your values file** (`my-values.yaml`):

```yaml
image:
  repository: ghcr.io/YOUR_USERNAME/gmocoin-exec-alert
  tag: "latest"  # or specific version like "v1.0.0"

gmocoin:
  apiKey: "your-api-key"
  apiSecret: "your-api-secret"

pagerduty:
  routingKey: "your-pagerduty-routing-key"

# Optional: Enable process monitoring
processMonitor:
  enabled: true
  pattern: "uv run atc"
```

2. **Install the chart**:

```bash
helm install gmocoin-exec-alert ./charts/gmocoin-exec-alert \
  -f my-values.yaml \
  --namespace monitoring \
  --create-namespace
```

3. **Or use `--set` for sensitive values**:

```bash
helm install gmocoin-exec-alert ./charts/gmocoin-exec-alert \
  --set gmocoin.apiKey="YOUR_API_KEY" \
  --set gmocoin.apiSecret="YOUR_API_SECRET" \
  --set pagerduty.routingKey="YOUR_ROUTING_KEY" \
  --namespace monitoring \
  --create-namespace
```

### Upgrade

```bash
helm upgrade gmocoin-exec-alert ./charts/gmocoin-exec-alert \
  -f my-values.yaml \
  --namespace monitoring
```

### Uninstall

```bash
helm uninstall gmocoin-exec-alert --namespace monitoring
```

### View Logs

```bash
kubectl logs -f deployment/gmocoin-exec-alert -n monitoring
```

## Notes

- This uses the GMO Coin `POST /private/v1/ws-auth` endpoint to mint a temporary access token, connects to:
  - `wss://api.coin.z.com/ws/private/v1/{ACCESS_TOKEN}`
- The server pings about once per minute; the client responds automatically.
- By default this subscribes to `executionEvents` only. You can override via `ALERT_CHANNELS`.
- The process monitor uses `ps aux` to find matching processes and works on Unix-like systems (Linux, macOS).
- In Kubernetes, the application runs as a non-root user (UID 1000) for security.
