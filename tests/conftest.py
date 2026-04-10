from __future__ import annotations

import subprocess
import sys
import threading
import time
from concurrent import futures
from pathlib import Path
from typing import Generator

import grpc
import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _generate_proto() -> None:
    gen_dir = ROOT / "generated"
    pb2 = gen_dir / "inference_pb2.py"
    if pb2.exists():
        return

    gen_dir.mkdir(exist_ok=True)
    (gen_dir / "__init__.py").touch()

    result = subprocess.run(
        [
            sys.executable, "-m", "grpc_tools.protoc",
            f"-I{ROOT / 'proto'}",
            f"--python_out={gen_dir}",
            f"--grpc_python_out={gen_dir}",
            str(ROOT / "proto" / "inference.proto"),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"proto generation failed:\n{result.stderr}")

    grpc_file = gen_dir / "inference_pb2_grpc.py"
    content = grpc_file.read_text()
    content = content.replace(
        "import inference_pb2", "from generated import inference_pb2"
    )
    grpc_file.write_text(content)


_generate_proto()
_BASE_PORT = 59100


def _next_port() -> int:
    global _BASE_PORT
    _BASE_PORT += 1
    return _BASE_PORT

def _start_server(server_id: str, port: int, delay_ms: float = 0.0) -> grpc.Server:
    from generated import inference_pb2_grpc
    from server.config import ServerConfig
    from server.main import InferenceServicer

    cfg = ServerConfig(
        host="127.0.0.1",
        port=port,
        server_id=server_id,
        artificial_delay_ms=delay_ms,
        artificial_delay_max_ms=0.0,
        output_rows=3,
        output_cols=2,
        log_level="WARNING",
    )
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    inference_pb2_grpc.add_InferenceServiceServicer_to_server(
        InferenceServicer(cfg), grpc_server
    )
    grpc_server.add_insecure_port(f"127.0.0.1:{port}")
    grpc_server.start()
    return grpc_server


@pytest.fixture()
def server1() -> Generator[tuple[str, grpc.Server], None, None]:
    port = _next_port()
    addr = f"127.0.0.1:{port}"
    srv = _start_server("server1", port)
    time.sleep(0.05)
    yield addr, srv
    srv.stop(grace=1)


@pytest.fixture()
def server2() -> Generator[tuple[str, grpc.Server], None, None]:
    port = _next_port()
    addr = f"127.0.0.1:{port}"
    srv = _start_server("server2", port)
    time.sleep(0.05)
    yield addr, srv
    srv.stop(grace=1)

def _start_gateway(backend_addrs: list[str], port: int) -> grpc.Server:
    from generated import inference_pb2_grpc
    from gateway.config import BackendConfig, GatewayConfig
    from gateway.main import GatewayServicer
    from gateway.router import Router

    backends = [
        BackendConfig(server_id=f"s{i}", address=addr)
        for i, addr in enumerate(backend_addrs, 1)
    ]
    cfg = GatewayConfig(
        host="127.0.0.1",
        port=port,
        backends=backends,
        health_check_interval_s=0.5,
        request_timeout_s=3.0,
        log_level="WARNING",
    )
    router = Router(cfg)
    router.start()
    time.sleep(0.7)

    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    inference_pb2_grpc.add_GatewayServiceServicer_to_server(
        GatewayServicer(router=router, cfg=cfg), grpc_server
    )
    grpc_server.add_insecure_port(f"127.0.0.1:{port}")
    grpc_server.start()
    return grpc_server, router


@pytest.fixture()
def gateway_with_backends(
    server1, server2
) -> Generator[tuple[str, grpc.Server], None, None]:
    addr1, srv1 = server1
    addr2, srv2 = server2
    port = _next_port()
    gw_addr = f"127.0.0.1:{port}"
    gw_server, router = _start_gateway([addr1, addr2], port)
    yield gw_addr, gw_server, router
    router.stop()
    gw_server.stop(grace=1)


@pytest.fixture()
def gateway_with_one_backend(
    server1,
) -> Generator[tuple[str, grpc.Server], None, None]:
    addr1, srv1 = server1
    port = _next_port()
    gw_addr = f"127.0.0.1:{port}"
    gw_server, router = _start_gateway([addr1], port)
    yield gw_addr, gw_server, router
    router.stop()
    gw_server.stop(grace=1)
