#!/usr/bin/env bash
# Usage: scripts/generate_proto.sh (from: inference-gateway/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$ROOT_DIR/proto"
OUT_DIR="$ROOT_DIR/generated"

mkdir -p "$OUT_DIR"
touch "$OUT_DIR/__init__.py"

echo "Generating gRPC stubs from proto/inference.proto ..."
python -m grpc_tools.protoc \
  -I "$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR/inference.proto"

sed -i 's/^import inference_pb2/from generated import inference_pb2/' \
  "$OUT_DIR/inference_pb2_grpc.py"

echo "Done. Generated files:"
ls -1 "$OUT_DIR"
