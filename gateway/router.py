from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import grpc

from gateway.config import BackendConfig, GatewayConfig
from gateway.transport import make_channel

logger = logging.getLogger(__name__)


@dataclass
class BackendState:
    config: BackendConfig
    channel: grpc.Channel
    healthy: bool = False
    last_check: str = ""
    consecutive_failures: int = 0


class Router:
    def __init__(self, cfg: GatewayConfig) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._rr_index: int = 0

        self._backends: List[BackendState] = [
            BackendState(
                config=bc,
                channel=make_channel(bc.address, cfg),
            )
            for bc in cfg.backends
        ]

        self._stop_event = threading.Event()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="health-checker"
        )

    def start(self) -> None:
        self._health_thread.start()
        logger.info(
            "Router started. Backends: %s",
            [b.config.address for b in self._backends],
        )

    def stop(self) -> None:
        self._stop_event.set()
        self._health_thread.join(timeout=5.0)
        for b in self._backends:
            b.channel.close()
        logger.info("Router stopped.")

    def pick_backend(self) -> Optional[BackendState]:
        with self._lock:
            healthy = [b for b in self._backends if b.healthy]
            if not healthy:
                return None
            backend = healthy[self._rr_index % len(healthy)]
            self._rr_index = (self._rr_index + 1) % len(healthy)
            logger.debug(
                "Picked backend %s (rr_index=%d, healthy=%d/%d)",
                backend.config.server_id,
                self._rr_index,
                len(healthy),
                len(self._backends),
            )
            return backend

    def get_status(self) -> List[dict]:
        with self._lock:
            return [
                {
                    "server_id": b.config.server_id,
                    "address": b.config.address,
                    "healthy": b.healthy,
                    "last_check": b.last_check,
                }
                for b in self._backends
            ]

    @property
    def rr_index(self) -> int:
        with self._lock:
            return self._rr_index

    # ─── Internal ────────────────────────────────────────────────────────

    def _health_loop(self) -> None:
        self._check_all()
        while not self._stop_event.wait(timeout=self._cfg.health_check_interval_s):
            self._check_all()

    def _check_all(self) -> None:
        for backend in self._backends:
            self._check_one(backend)

    def _check_one(self, backend: BackendState) -> None:
        from generated import inference_pb2, inference_pb2_grpc

        now = datetime.now(tz=timezone.utc).isoformat()
        try:
            stub = inference_pb2_grpc.InferenceServiceStub(backend.channel)
            resp = stub.HealthCheck(
                inference_pb2.HealthCheckRequest(service="inference"),
                timeout=self._cfg.health_check_interval_s * 0.8,
            )
            is_healthy = (
                resp.status == inference_pb2.HealthCheckResponse.Status.Value("SERVING")
            )
        except grpc.RpcError as e:
            logger.warning(
                "HealthCheck failed for %s (%s): %s",
                backend.config.server_id,
                backend.config.address,
                e.details() if hasattr(e, "details") else str(e),
            )
            is_healthy = False
        except Exception as e:
            logger.warning("HealthCheck error for %s: %s", backend.config.server_id, e)
            is_healthy = False

        with self._lock:
            was_healthy = backend.healthy
            backend.healthy = is_healthy
            backend.last_check = now
            if is_healthy:
                backend.consecutive_failures = 0
            else:
                backend.consecutive_failures += 1

        if was_healthy != is_healthy:
            if is_healthy:
                logger.info(
                    "[%s] RECOVERED at %s", backend.config.server_id, backend.config.address
                )
            else:
                logger.warning(
                    "[%s] DOWN at %s", backend.config.server_id, backend.config.address
                )
