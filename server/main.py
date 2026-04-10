from __future__ import annotations

import logging
import math
import random
import signal
import sys
import time
from concurrent import futures
from typing import Optional

import grpc

from server.config import ServerConfig, load_server_config

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s (%(funcName)s): %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=getattr(logging, level.upper(), logging.INFO),
    )


class InferenceServicer:
    """InferenceService implementation (dummy)."""

    def __init__(self, cfg: ServerConfig) -> None:
        self._cfg = cfg

    def _apply_delay(self) -> float:
        delay_ms = self._cfg.artificial_delay_ms
        if self._cfg.artificial_delay_max_ms > 0:
            delay_ms += random.uniform(0, self._cfg.artificial_delay_max_ms)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        return delay_ms

    def _dummy_output(self) -> list[float]:
        """
        Generate dummy output data based on a sin wave pattern.
        """
        rows, cols = self._cfg.output_rows, self._cfg.output_cols
        t = time.time()
        return [
            math.sin(t + r * 0.3 + c * 0.1)
            for r in range(rows)
            for c in range(cols)
        ]

    def Predict(self, request, context):
        from generated import inference_pb2

        req_id = request.request_id
        n_images = len(request.images)
        n_pos = len(request.position)
        logger.info(
            "[%s] Predict: images=%d, position_len=%d", req_id, n_images, n_pos
        )

        t0 = time.monotonic()
        delay_ms = self._apply_delay()
        data = self._dummy_output()
        elapsed_ms = (time.monotonic() - t0) * 1000

        logger.info(
            "[%s] Responding: rows=%d cols=%d delay=%.1f ms total=%.1f ms",
            req_id,
            self._cfg.output_rows,
            self._cfg.output_cols,
            delay_ms,
            elapsed_ms,
        )
        return inference_pb2.PredictResponse(
            request_id=req_id,
            rows=self._cfg.output_rows,
            cols=self._cfg.output_cols,
            data=data,
            server_id=self._cfg.server_id,
            processing_time_ms=elapsed_ms,
            status="ok",
            metadata={
                "server_id": self._cfg.server_id,
                "n_images": str(n_images),
                "n_position": str(n_pos),
                "artificial_delay_ms": f"{delay_ms:.1f}",
            },
        )

    def HealthCheck(self, request, context):
        from generated import inference_pb2

        logger.debug("HealthCheck from %s", context.peer())
        return inference_pb2.HealthCheckResponse(
            status=inference_pb2.HealthCheckResponse.Status.Value("SERVING"),
            message=f"{self._cfg.server_id} is serving",
        )

    def Ping(self, request, context):
        from generated import inference_pb2

        logger.info("Ping: '%s' from %s", request.message, context.peer())
        return inference_pb2.PingResponse(
            message=f"pong from {self._cfg.server_id}: {request.message}",
            server_id=self._cfg.server_id,
            timestamp_ms=int(time.time() * 1000),
        )


def _add_servicer(server: grpc.Server, servicer: InferenceServicer) -> None:
    from generated import inference_pb2_grpc

    inference_pb2_grpc.add_InferenceServiceServicer_to_server(servicer, server)


def serve(cfg: Optional[ServerConfig] = None) -> None:
    if cfg is None:
        cfg = load_server_config()
    _setup_logging(cfg.log_level)

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=4),
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
        ],
    )

    servicer = InferenceServicer(cfg)
    _add_servicer(server, servicer)

    listen_addr = f"{cfg.host}:{cfg.port}"
    server.add_insecure_port(listen_addr)
    server.start()

    logger.info(
        "Server [%s] listening on %s  delay=%.0fms (max +%.0fms)  output=%dx%d",
        cfg.server_id,
        listen_addr,
        cfg.artificial_delay_ms,
        cfg.artificial_delay_max_ms,
        cfg.output_rows,
        cfg.output_cols,
    )

    def _shutdown(signum, frame):
        logger.info("[%s] Shutting down ...", cfg.server_id)
        server.stop(grace=2)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
