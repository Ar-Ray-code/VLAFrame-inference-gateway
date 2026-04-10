from __future__ import annotations

import time

import grpc
import pytest


def test_server_ping_direct(server1):
    from generated import inference_pb2, inference_pb2_grpc

    addr, _ = server1
    channel = grpc.insecure_channel(addr)
    stub = inference_pb2_grpc.InferenceServiceStub(channel)
    resp = stub.Ping(inference_pb2.PingRequest(message="hello"), timeout=3.0)
    channel.close()

    assert resp.server_id == "server1"
    assert "pong" in resp.message
    assert resp.timestamp_ms > 0


def test_server_health_check_direct(server1):
    from generated import inference_pb2, inference_pb2_grpc

    addr, _ = server1
    channel = grpc.insecure_channel(addr)
    stub = inference_pb2_grpc.InferenceServiceStub(channel)
    resp = stub.HealthCheck(
        inference_pb2.HealthCheckRequest(service="inference"), timeout=3.0
    )
    channel.close()

    assert resp.status == inference_pb2.HealthCheckResponse.Status.Value("SERVING")


def test_gateway_ping(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)
    resp = stub.Ping(inference_pb2.PingRequest(message="gateway-test"), timeout=5.0)
    channel.close()

    assert resp.server_id in ("server1", "server2")
    assert "pong" in resp.message


def test_gateway_health_check(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)
    resp = stub.HealthCheck(
        inference_pb2.HealthCheckRequest(service="gateway"), timeout=5.0
    )
    channel.close()

    assert resp.status == inference_pb2.HealthCheckResponse.Status.Value("SERVING")


def test_gateway_list_servers(gateway_with_backends):
    from generated import inference_pb2, inference_pb2_grpc

    gw_addr, _, _ = gateway_with_backends
    channel = grpc.insecure_channel(gw_addr)
    stub = inference_pb2_grpc.GatewayServiceStub(channel)
    resp = stub.ListServers(inference_pb2.ListServersRequest(), timeout=5.0)
    channel.close()

    assert len(resp.servers) == 2
    # 少なくとも 1 台は healthy
    assert any(s.healthy for s in resp.servers)
