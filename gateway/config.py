from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class BackendConfig:
    server_id: str
    address: str  # host:port


@dataclass
class GatewayConfig:
    host: str
    port: int
    backends: List[BackendConfig]
    health_check_interval_s: float
    request_timeout_s: float
    log_level: str

    # ─── For TLS ───────────────────────────────────────────────
    tls_enabled: bool = False
    tls_ca_cert: str = ""
    tls_client_cert: str = ""
    tls_client_key: str = ""
    # ───────────────────────────────────────────────────


def _parse_backends(raw: str) -> List[BackendConfig]:
    backends: List[BackendConfig] = []
    for i, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            sid, addr = item.split("=", 1)
        else:
            sid, addr = f"server{i}", item
        backends.append(BackendConfig(server_id=sid.strip(), address=addr.strip()))
    return backends


def load_config() -> GatewayConfig:
    backends_raw = os.environ.get(
        "BACKEND_SERVERS", "server1=localhost:50052,server2=localhost:50053"
    )
    return GatewayConfig(
        host=os.environ.get("GATEWAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("GATEWAY_PORT", "50051")),
        backends=_parse_backends(backends_raw),
        health_check_interval_s=float(
            os.environ.get("HEALTH_CHECK_INTERVAL_S", "5.0")
        ),
        request_timeout_s=float(os.environ.get("REQUEST_TIMEOUT_S", "10.0")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        tls_enabled=os.environ.get("TLS_ENABLED", "false").lower() == "true",
        tls_ca_cert=os.environ.get("TLS_CA_CERT", ""),
        tls_client_cert=os.environ.get("TLS_CLIENT_CERT", ""),
        tls_client_key=os.environ.get("TLS_CLIENT_KEY", ""),
    )
