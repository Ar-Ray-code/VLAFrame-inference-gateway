from __future__ import annotations

import logging
import signal
import sys
import time
from concurrent import futures
from typing import Optional

import grpc

from gateway.config import GatewayConfig, load_config
from gateway.router import Router
from gateway.transport import make_server_credentials

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=getattr(logging, level.upper(), logging.INFO),
    )


class GatewayServicer:
    def __init__(self, router: Router, cfg: GatewayConfig) -> None:
        self._router = router
        self._cfg = cfg

    def Predict(self, request, context):
        from generated import inference_pb2, inference_pb2_grpc

        req_id = request.request_id
        logger.info("[%s] Predict received", req_id)

        backend = self._router.pick_backend()
        if backend is None:
            logger.error("[%s] No healthy backends available", req_id)
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("No healthy backends available")
            return inference_pb2.PredictResponse(
                request_id=req_id,
                status="error",
                metadata={"error": "No healthy backends available"},
            )

        logger.info("[%s] Forwarding to %s (%s)", req_id, backend.config.server_id, backend.config.address)
        t0 = time.monotonic()
        try:
            stub = inference_pb2_grpc.InferenceServiceStub(backend.channel)
            resp = stub.Predict(request, timeout=self._cfg.request_timeout_s)
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[%s] Response from %s in %.1f ms (status=%s)",
                req_id, backend.config.server_id, elapsed_ms, resp.status,
            )
            return resp
        except grpc.RpcError as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            code = e.code() if hasattr(e, "code") else "UNKNOWN"
            detail = e.details() if hasattr(e, "details") else str(e)
            logger.error(
                "[%s] RPC error from %s after %.1f ms: %s %s",
                req_id, backend.config.server_id, elapsed_ms, code, detail,
            )
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Backend {backend.config.server_id} error: {detail}")
            return inference_pb2.PredictResponse(
                request_id=req_id,
                status="error",
                metadata={"error": detail, "backend": backend.config.server_id},
            )

    def HealthCheck(self, request, context):
        from generated import inference_pb2

        healthy_count = sum(1 for b in self._router.get_status() if b["healthy"])
        total = len(self._router.get_status())
        if healthy_count > 0:
            return inference_pb2.HealthCheckResponse(
                status=inference_pb2.HealthCheckResponse.Status.Value("SERVING"),
                message=f"Gateway OK ({healthy_count}/{total} backends healthy)",
            )
        return inference_pb2.HealthCheckResponse(
            status=inference_pb2.HealthCheckResponse.Status.Value("NOT_SERVING"),
            message="No healthy backends",
        )

    def Ping(self, request, context):
        from generated import inference_pb2, inference_pb2_grpc
        import time as _time

        req_id = "ping"
        backend = self._router.pick_backend()
        if backend is None:
            return inference_pb2.PingResponse(
                message="gateway-pong (no healthy backends)",
                server_id="gateway",
                timestamp_ms=int(_time.time() * 1000),
            )
        try:
            stub = inference_pb2_grpc.InferenceServiceStub(backend.channel)
            resp = stub.Ping(request, timeout=self._cfg.request_timeout_s)
            return resp
        except grpc.RpcError as e:
            return inference_pb2.PingResponse(
                message=f"gateway-error: {e.details() if hasattr(e, 'details') else e}",
                server_id="gateway",
                timestamp_ms=int(_time.time() * 1000),
            )

    def ListServers(self, request, context):
        from generated import inference_pb2

        status = self._router.get_status()
        servers = [
            inference_pb2.ServerInfo(
                server_id=s["server_id"],
                address=s["address"],
                healthy=s["healthy"],
                last_check=s["last_check"],
            )
            for s in status
        ]
        return inference_pb2.ListServersResponse(
            servers=servers,
            round_robin_index=self._router.rr_index,
        )


def _add_servicer(server: grpc.Server, servicer: GatewayServicer) -> None:
    from generated import inference_pb2_grpc

    inference_pb2_grpc.add_GatewayServiceServicer_to_server(servicer, server)


def serve(cfg: Optional[GatewayConfig] = None) -> None:
    if cfg is None:
        cfg = load_config()
    _setup_logging(cfg.log_level)

    router = Router(cfg)
    router.start()

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
        ],
    )

    servicer = GatewayServicer(router=router, cfg=cfg)
    _add_servicer(server, servicer)

    creds = make_server_credentials(cfg)
    listen_addr = f"{cfg.host}:{cfg.port}"
    if creds is None:
        server.add_insecure_port(listen_addr)
    else:
        server.add_secure_port(listen_addr, creds)

    server.start()
    logger.info("Gateway listening on %s (TLS=%s)", listen_addr, cfg.tls_enabled)
    logger.info(
        "Backends: %s",
        [f"{b.server_id}={b.address}" for b in cfg.backends],
    )

    def _shutdown(signum, frame):
        logger.info("Shutting down gateway ...")
        router.stop()
        server.stop(grace=3)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    serve()
