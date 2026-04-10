from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    host: str
    port: int
    server_id: str
    artificial_delay_ms: float # simulated latency (0 = no delay)
    artificial_delay_max_ms: float  # additional random delay up to this value (0 = no additional random delay)
    output_rows: int
    output_cols: int
    log_level: str


def load_server_config() -> ServerConfig:
    return ServerConfig(
        host=os.environ.get("SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "50052")),
        server_id=os.environ.get("SERVER_ID", "server1"),
        artificial_delay_ms=float(os.environ.get("ARTIFICIAL_DELAY_MS", "0")),
        artificial_delay_max_ms=float(os.environ.get("ARTIFICIAL_DELAY_MAX_MS", "0")),
        output_rows=int(os.environ.get("OUTPUT_ROWS", "6")),
        output_cols=int(os.environ.get("OUTPUT_COLS", "1")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
