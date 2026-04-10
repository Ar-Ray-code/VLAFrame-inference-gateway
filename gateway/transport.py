from __future__ import annotations

import grpc

from gateway.config import GatewayConfig


def make_channel(address: str, cfg: GatewayConfig) -> grpc.Channel:
    if cfg.tls_enabled:
        # ─── TLS ─────────────────────────────
        # TODO: support TLS with client certs if needed
        # credentials = grpc.ssl_channel_credentials(
        #     root_certificates=open(cfg.tls_ca_cert, "rb").read(),
        #     private_key=open(cfg.tls_client_key, "rb").read() if cfg.tls_client_key else None,
        #     certificate_chain=open(cfg.tls_client_cert, "rb").read() if cfg.tls_client_cert else None,
        # )
        # return grpc.secure_channel(address, credentials)
        raise NotImplementedError("TLS is not yet implemented")
    return grpc.insecure_channel(address)


def make_server_credentials(cfg: GatewayConfig) -> grpc.ServerCredentials | None:
    if cfg.tls_enabled:
        raise NotImplementedError("TLS is not yet implemented")
    return None
