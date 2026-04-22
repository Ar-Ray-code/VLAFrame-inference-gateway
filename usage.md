# inference-gateway

gRPC-based inference gateway.
`CLI → inference-gateway → server1 / server2`


## Generate Proto Code

```bash
cd inference-gateway

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Generate proto code
bash scripts/generate_proto.sh
```


## Starting the Services

#### 1. Deploy to a Remote Machine

Clone the repository on the remote machine, then start the server with `docker-compose.server.yml`.

```bash
# On the remote machine
git clone https://github.com/Ar-Ray-code/VLAFrame-inference-gateway.git
cd VLAFrame-inference-gateway

SERVER_ID=remote1 OUTPUT_COLS=3 \
  docker compose -f docker-compose.server.yml up --build -d
```

#### 2. Start Local Server + Gateway on Host PC

```bash
cd inference-gateway

# Start local server
SERVER_ID=local1 OUTPUT_COLS=3 \
  docker compose -f docker-compose.server.yml up --build -d

# Start gateway pointing to both local and remote backends
BACKEND_SERVERS="local1=10.42.0.1:50052,remote1=10.42.0.2:50052" \
  docker compose -f docker-compose.gateway.yml up --build -d
```

#### 3. Verify with the CLI

```bash
# List servers — local1 and remote1 should both show as healthy
uv run python -m cli.main servers

# Connectivity check
uv run python -m cli.main ping

# Inference request — check server_id in the response to confirm routing
uv run python -m cli.main predict --image assets/sample.png --position 0.1,0.2,0.3
```

#### 4. Stop / Restart

Restarting the host PC's server and gateway will automatically reconnect to the remote server after the next health check cycle.

```bash
# Stop host PC services only
docker compose -f docker-compose.server.yml down
BACKEND_SERVERS=dummy docker compose -f docker-compose.gateway.yml down

# Restart
SERVER_ID=local1 OUTPUT_COLS=3 docker compose -f docker-compose.server.yml up --build -d
BACKEND_SERVERS="local1=10.42.0.1:50052,remote1=10.42.0.2:50052" \
  docker compose -f docker-compose.gateway.yml up --build -d
```

#### Customize Server Output via Environment Variables

```bash
SERVER_ID=remote1 \
ARTIFICIAL_DELAY_MS=50 \
OUTPUT_ROWS=6 OUTPUT_COLS=3 \
  docker compose -f docker-compose.server.yml up --build -d
```


## Running the Gateway as a Persistent Service

### Option A: Docker Compose (recommended)

The gateway container already has `restart: unless-stopped`, so it survives reboots as long as the Docker daemon starts on boot.

Store the configuration in a `.env` file in the project root so you do not have to pass environment variables on every `docker compose` invocation:

**`.env` (gateway)**
```env
# Backend servers — required
BACKEND_SERVERS=local1=10.42.0.1:50052,remote1=10.42.0.2:50052

# Gateway listen settings
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=50051

# Routing behaviour
HEALTH_CHECK_INTERVAL_S=5
REQUEST_TIMEOUT_S=10

# Logging
LOG_LEVEL=INFO
```

Start (or restart) the gateway using the `.env` file:

```bash
# First start
docker compose -f docker-compose.gateway.yml up --build -d

# Apply configuration changes
docker compose -f docker-compose.gateway.yml up --build -d --force-recreate

# Check status
docker compose -f docker-compose.gateway.yml ps
docker compose -f docker-compose.gateway.yml logs -f gateway
```

Docker reads the `.env` file automatically when it is placed next to the compose file.


### Option B: systemd Unit (bare-metal / without Docker)

Use this approach when running `python -m gateway.main` directly on the host.

**`/etc/inference-gateway/gateway.env`**
```env
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=50051
BACKEND_SERVERS=local1=10.42.0.1:50052,remote1=10.42.0.2:50052
HEALTH_CHECK_INTERVAL_S=5
REQUEST_TIMEOUT_S=10
LOG_LEVEL=INFO
```

**`/etc/systemd/system/inference-gateway.service`**
```ini
[Unit]
Description=VLAFrame Inference Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/inference-gateway
EnvironmentFile=/etc/inference-gateway/gateway.env
ExecStart=/home/ubuntu/inference-gateway/.venv/bin/python -m gateway.main
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable inference-gateway
sudo systemctl start inference-gateway

# Check status and logs
sudo systemctl status inference-gateway
sudo journalctl -u inference-gateway -f
```

Update environment variables by editing `/etc/inference-gateway/gateway.env`, then restart:

```bash
sudo systemctl restart inference-gateway
```


## CLI Usage Examples

```bash
# Connectivity check
uv run python -m cli.main ping

# Health check
uv run python -m cli.main health

# List backend servers
uv run python -m cli.main servers

# Inference request (image + position array)
uv run python -m cli.main predict \
  --image assets/sample.png \
  --position 0.1,0.2,0.3,0.4,0.5,0.6

# Multiple images in a single request
uv run python -m cli.main predict \
  --image assets/sample.png \
  --image assets/sample.png \
  --position 1.0,2.0,3.0

# Target a specific gateway address
uv run python -m cli.main --gateway 10.42.0.1:50051 ping
```

### Example CLI Output

```
  request_id    : a795363c
  gateway       : localhost:50051
  server_id     : remote1          ← which backend handled the request
  status        : ok
  elapsed       : 12.4 ms
  proc_time     : 0.0 ms (server-side)
  output shape  : 6 x 3

  Output [6x3] (showing col0)     ← only col0 is shown when cols > 1
   col0
  ─────────
  -0.1928
  -0.4742
  -0.7132
  -0.8885
  -0.9844
  -0.9924
```


## Behavior When a Backend Goes Down

1. Stop a backend (e.g., `docker compose stop server1`)
2. The gateway's health check (default 5-second interval) detects the backend is DOWN
3. Subsequent requests are automatically routed to the remaining healthy backend(s)

```bash
# CLI continues to work after server1 goes down
uv run python -m cli.main predict --image assets/sample.png --position 0.0,0.0,0.0
# → server_id: server2
```


## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_HOST` | `0.0.0.0` | Gateway listen host |
| `GATEWAY_PORT` | `50051` | Gateway listen port |
| `BACKEND_SERVERS` | `server1=localhost:50052,server2=localhost:50053` | Backend list (`id=host:port`, comma-separated) |
| `HEALTH_CHECK_INTERVAL_S` | `5.0` | Health check interval (seconds) |
| `REQUEST_TIMEOUT_S` | `10.0` | Request timeout (seconds) |
| `LOG_LEVEL` | `INFO` | Log level |
| `SERVER_ID` | `server1` | Server identifier |
| `SERVER_PORT` | `50052` | Server listen port |
| `ARTIFICIAL_DELAY_MS` | `0` | Fixed artificial delay (ms) |
| `ARTIFICIAL_DELAY_MAX_MS` | `0` | Maximum random artificial delay (ms) |
| `OUTPUT_ROWS` | `6` | Number of rows in server output |
| `OUTPUT_COLS` | `1` | Number of columns in server output |
| `GATEWAY_ADDR` | `localhost:50051` | CLI target address |


## Running Tests

```bash
cd inference-gateway
uv run pytest tests/ -v
```

The test suite covers:
- Direct server Ping / HealthCheck
- Gateway-forwarded Ping / HealthCheck / ListServers
- Gateway-forwarded Predict (single image and multiple images)
- Round-robin distribution across two backends
- Continued operation with one backend down (failover)
- Error response when all backends are down


## Known Limitations

- **No encryption**: All traffic is currently plaintext. Intended for LAN-only demo use.
- **No authentication**: Anyone can connect to the gateway.
- **No service discovery**: Backend list is fixed at startup via environment variable.
- **Stateless**: Round-robin state resets on gateway restart.
- **No real inference**: The server always returns dummy sinusoidal data.

