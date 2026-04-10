"""
inference-gateway CLI。
usage:
    python -m cli.main ping
    python -m cli.main servers
    python -m cli.main predict --image assets/sample.png --position 0.1,0.2,0.3
    python -m cli.main predict --image img1.png --image img2.png --position 1.0,2.0
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

import click
import grpc
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# ─── Proto import helper ─────────────────────────────────────────────────────

def _get_stubs(gateway_addr: str):
    from generated import inference_pb2_grpc  # noqa: PLC0415

    channel = grpc.insecure_channel(
        gateway_addr,
        options=[
            ("grpc.max_send_message_length", 50 * 1024 * 1024),
            ("grpc.max_receive_message_length", 50 * 1024 * 1024),
        ],
    )
    stub = inference_pb2_grpc.GatewayServiceStub(channel)
    return channel, stub


# ─── CLI group ───────────────────────────────────────────────────────────────

@click.group()
@click.option(
    "--gateway",
    envvar="GATEWAY_ADDR",
    default="localhost:50051",
    show_default=True,
    help="Gateway address (host:port)",
)
@click.pass_context
def cli(ctx: click.Context, gateway: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["gateway"] = gateway


# ─── ping ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--message", default="hello", help="Ping message")
@click.pass_context
def ping(ctx: click.Context, message: str) -> None:
    from generated import inference_pb2  # noqa: PLC0415

    gateway = ctx.obj["gateway"]
    channel, stub = _get_stubs(gateway)
    t0 = time.monotonic()
    try:
        resp = stub.Ping(
            inference_pb2.PingRequest(message=message),
            timeout=5.0,
        )
        elapsed = (time.monotonic() - t0) * 1000
        console.print(f"[green]Pong![/green]  server_id=[bold]{resp.server_id}[/bold]  "
                      f"msg=[italic]{resp.message}[/italic]  "
                      f"elapsed=[cyan]{elapsed:.1f} ms[/cyan]")
    except grpc.RpcError as e:
        console.print(f"[red]Ping failed:[/red] {e.details() if hasattr(e, 'details') else e}")
        sys.exit(1)
    finally:
        channel.close()


# ─── servers ─────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def servers(ctx: click.Context) -> None:
    from generated import inference_pb2  # noqa: PLC0415

    gateway = ctx.obj["gateway"]
    channel, stub = _get_stubs(gateway)
    try:
        resp = stub.ListServers(inference_pb2.ListServersRequest(), timeout=5.0)
        table = Table(title="Backend Servers", box=box.ROUNDED)
        table.add_column("Server ID", style="bold")
        table.add_column("Address")
        table.add_column("Healthy")
        table.add_column("Last Check")
        for s in resp.servers:
            healthy_str = "[green]✓ healthy[/green]" if s.healthy else "[red]✗ down[/red]"
            table.add_row(s.server_id, s.address, healthy_str, s.last_check)
        table.caption = f"Round-robin index: {resp.round_robin_index}"
        console.print(table)
    except grpc.RpcError as e:
        console.print(f"[red]ListServers failed:[/red] {e.details() if hasattr(e, 'details') else e}")
        sys.exit(1)
    finally:
        channel.close()


# ─── predict ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--image", "image_paths",
    multiple=True,
    type=click.Path(exists=True, readable=True),
    help="Image file path (can specify multiple times)",
)
@click.option(
    "--position",
    default="0.0",
    help="Position values as comma-separated floats (e.g. 0.1,0.2,0.3)",
)
@click.option("--request-id", default=None, help="request_id to correlate logs (default: random UUID)")
@click.option("--timeout", default=10.0, show_default=True, help="timeout for the Predict request in seconds")
@click.pass_context
def predict(
    ctx: click.Context,
    image_paths: tuple[str, ...],
    position: str,
    request_id: Optional[str],
    timeout: float,
) -> None:
    from generated import inference_pb2  # noqa: PLC0415

    gateway = ctx.obj["gateway"]
    req_id = request_id or str(uuid.uuid4())[:8]
    pos_values: List[float] = [float(v) for v in position.split(",") if v.strip()]

    images: List[inference_pb2.Image] = []
    for path in image_paths:
        _load_image(path, images, inference_pb2)

    if not images:
        console.print("[yellow]No images specified, sending dummy image data.[/yellow]")
        images.append(
            inference_pb2.Image(
                data=bytes([128, 128, 128]),
                width=1, height=1, format="rgb",
            )
        )

    req = inference_pb2.PredictRequest(
        request_id=req_id,
        timestamp_ms=int(time.time() * 1000),
        images=images,
        position=pos_values,
        metadata={"cli_version": "1.0"},
    )

    channel, stub = _get_stubs(gateway)
    t0 = time.monotonic()
    try:
        resp = stub.Predict(req, timeout=timeout)
        elapsed = (time.monotonic() - t0) * 1000

        _print_predict_result(resp, req_id, gateway, elapsed)

        if resp.status != "ok":
            sys.exit(1)
    except grpc.RpcError as e:
        elapsed = (time.monotonic() - t0) * 1000
        console.print(
            f"[red]Predict failed[/red] (request_id={req_id}, {elapsed:.0f} ms): "
            f"{e.details() if hasattr(e, 'details') else e}"
        )
        sys.exit(1)
    finally:
        channel.close()


def _load_image(
    path: str,
    images: list,
    inference_pb2,
) -> None:
    try:
        from PIL import Image as PILImage  # noqa: PLC0415

        img = PILImage.open(path).convert("RGB")
        w, h = img.size
        images.append(
            inference_pb2.Image(
                data=img.tobytes(),
                width=w,
                height=h,
                format="rgb",
            )
        )
        console.print(f"  Loaded image: [cyan]{path}[/cyan]  ({w}x{h})")
    except Exception as e:
        console.print(f"[red]Error: read image[/red] {path}: {e}")
        raise SystemExit(1)


def _print_predict_result(resp, req_id: str, gateway: str, elapsed_ms: float) -> None:
    """推論結果を見やすく表示する。"""
    status_str = (
        "[green]ok[/green]" if resp.status == "ok" else f"[red]{resp.status}[/red]"
    )
    console.print()
    console.print(f"  [bold]request_id[/bold]    : {req_id}")
    console.print(f"  [bold]gateway[/bold]       : {gateway}")
    console.print(f"  [bold]server_id[/bold]     : [bold cyan]{resp.server_id}[/bold cyan]")
    console.print(f"  [bold]status[/bold]        : {status_str}")
    console.print(f"  [bold]elapsed[/bold]       : [cyan]{elapsed_ms:.1f} ms[/cyan]")
    console.print(f"  [bold]proc_time[/bold]     : {resp.processing_time_ms:.1f} ms (server-side)")
    console.print(f"  [bold]output shape[/bold]  : {resp.rows} x {resp.cols}")

    if resp.data:
        if resp.cols == 1:
            table = Table(title=f"Output [{resp.rows}x{resp.cols}]", box=box.SIMPLE)
            table.add_column("col0", justify="right")
            for r in range(resp.rows):
                table.add_row(f"{resp.data[r]:.4f}")
        else:
            table = Table(
                title=f"Output [{resp.rows}x{resp.cols}] (showing col0)",
                box=box.SIMPLE,
            )
            table.add_column("col0", justify="right")
            for r in range(resp.rows):
                table.add_row(f"{resp.data[r * resp.cols]:.4f}")
        console.print(table)

    if resp.metadata:
        console.print("  [bold]metadata[/bold]:")
        for k, v in resp.metadata.items():
            console.print(f"    {k}: {v}")
    console.print()


# ─── health ──────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def health(ctx: click.Context) -> None:
    """gateway のヘルス状態を確認する。"""
    from generated import inference_pb2  # noqa: PLC0415

    gateway = ctx.obj["gateway"]
    channel, stub = _get_stubs(gateway)
    try:
        resp = stub.HealthCheck(
            inference_pb2.HealthCheckRequest(service="gateway"),
            timeout=5.0,
        )
        status_name = inference_pb2.HealthCheckResponse.Status.Name(resp.status)
        color = "green" if status_name == "SERVING" else "red"
        console.print(f"[{color}]{status_name}[/{color}]: {resp.message}")
    except grpc.RpcError as e:
        console.print(f"[red]HealthCheck failed:[/red] {e.details() if hasattr(e, 'details') else e}")
        sys.exit(1)
    finally:
        channel.close()


if __name__ == "__main__":
    cli()
