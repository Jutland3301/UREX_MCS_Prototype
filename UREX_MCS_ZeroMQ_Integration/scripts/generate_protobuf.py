from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schema"
PROTO_FILES = [SCHEMA_DIR / "urex.proto", SCHEMA_DIR / "integration.proto"]
PYTHON_OUT = ROOT / "packet" / "generated"


def compiler_prefix() -> list[str]:
    protoc = shutil.which("protoc")
    if protoc:
        return [protoc]
    if importlib.util.find_spec("grpc_tools.protoc") is not None:
        return [sys.executable, "-m", "grpc_tools.protoc"]
    raise SystemExit(
        "No Protocol Buffers compiler found. Install protoc or "
        "`python -m pip install -r requirements-dev.txt`."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate UREX Protocol Buffers language bindings."
    )
    parser.add_argument(
        "--cpp-out",
        type=Path,
        help="also generate C++ bindings into this directory",
    )
    args = parser.parse_args()

    PYTHON_OUT.mkdir(parents=True, exist_ok=True)
    command = compiler_prefix() + [
        f"-I{SCHEMA_DIR}",
        f"--python_out={PYTHON_OUT}",
    ]
    if args.cpp_out is not None:
        cpp_out = args.cpp_out.resolve()
        cpp_out.mkdir(parents=True, exist_ok=True)
        command.append(f"--cpp_out={cpp_out}")
    command.extend(str(path) for path in PROTO_FILES)

    subprocess.run(command, cwd=ROOT, check=True)
    print("Generated Python bindings from schema/urex.proto and schema/integration.proto")
    if args.cpp_out is not None:
        print(f"Generated C++ binding in {args.cpp_out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
