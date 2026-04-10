from __future__ import annotations

import time
import uuid
from concurrent import futures

import grpc
import pytest


def _make_request(req_id: str | None = None):
    from generated import inference_pb2

    return inference_pb2.PredictRequest(
        request_id=req_id or str(uuid.uuid4())[:8],
        timestamp_ms=int(time.time() * 1000),
        images=[
            inference_pb2.Image(
                data=bytes([128, 64, 32]),
                width=1, height=1, format="rgb",
            )
        ],
        position=[0.1, 0.2, 0.3],
        metadata={"test": "true"},
    )


def test_predict_direct(server1):
    from generated import inference_pb2, inference_pb2_grpc

    addr, _ = server1
    channel = grpc.insecure_channel(addr)
    stub = inference_pb2_grpc.InferenceServiceStub(channel)
    resp = stub.Predict(_make_request("direct-001"), timeout=5.0)
    channel.close()

    assert resp.status == "ok"
    assert resp.server_id == "server1"
    assert resp.rows == 3
    assert resp.cols == 2
    assert len(resp.data) == 6  # 3x2


def test_predict_via_gateway(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)
    resp = stub.Predict(_make_request("gw-001"), timeout=5.0)
    channel.close()

    assert resp.status == "ok"
    assert resp.server_id in ("server1", "server2")
    assert len(resp.data) == 6


def test_round_robin(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)

    server_ids = set()
    for i in range(6):
        resp = stub.Predict(_make_request(f"rr-{i:03d}"), timeout=5.0)
        assert resp.status == "ok"
        server_ids.add(resp.server_id)

    channel.close()

    assert "server1" in server_ids and "server2" in server_ids, \
        f"Expected both server1 and server2, got {server_ids}"


def test_failover_when_backend_down(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, gw_srv, router = gateway_with_backends

    backends = router._backends
    backends[0].channel.close()

    time.sleep(1.0)

    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)

    server_ids = set()
    for i in range(4):
        try:
            resp = stub.Predict(_make_request(f"fo-{i:03d}"), timeout=5.0)
            if resp.status == "ok":
                server_ids.add(resp.server_id)
        except grpc.RpcError:
            pass

    channel.close()
    assert "server2" in server_ids, f"Expected server2 in server_ids, got {server_ids}"


def test_multiple_images(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)

    req = inference_pb2.PredictRequest(
        request_id="multi-img",
        timestamp_ms=int(time.time() * 1000),
        images=[
            inference_pb2.Image(data=bytes([r, g, b]), width=1, height=1, format="rgb")
            for r, g, b in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        ],
        position=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    )
    resp = stub.Predict(req, timeout=5.0)
    channel.close()

    assert resp.status == "ok"
    assert resp.metadata.get("n_images") == "3"
    assert resp.metadata.get("n_position") == "6"


def test_no_healthy_backends():
    from concurrent import futures as cf
    from generated import inference_pb2, inference_pb2_grpc
    from gateway.config import BackendConfig, GatewayConfig
    from gateway.main import GatewayServicer
    from gateway.router import Router

    port = 59200
    backends = [BackendConfig(server_id="dead", address="127.0.0.1:1")]
    cfg = GatewayConfig(
        host="127.0.0.1",
        port=port,
        backends=backends,
        health_check_interval_s=0.3,
        request_timeout_s=2.0,
        log_level="WARNING",
    )
    router = Router(cfg)
    router.start()
    time.sleep(0.5)

    grpc_server = grpc.server(cf.ThreadPoolExecutor(max_workers=2))
    inference_pb2_grpc.add_GatewayServiceServicer_to_server(
        GatewayServicer(router=router, cfg=cfg), grpc_server
    )
    grpc_server.add_insecure_port(f"127.0.0.1:{port}")
    grpc_server.start()

    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = inference_pb2_grpc.GatewayServiceStub(channel)

    try:
        resp = stub.Predict(_make_request("no-backend"), timeout=3.0)
        # UNAVAILABLE か status=error のどちらか
        assert resp.status == "error"
    except grpc.RpcError as e:
        assert e.code() == grpc.StatusCode.UNAVAILABLE
    finally:
        channel.close()
        router.stop()
        grpc_server.stop(grace=1)
