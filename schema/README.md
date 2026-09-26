# UREX Protocol Buffers schema

`urex.proto` is the authoritative cross-language packet definition for v0.3.b.
The PySide6 GUI does not define the wire representation.

Generate the Python binding with:

```bash
python -m pip install -r requirements-dev.txt
python scripts/generate_protobuf.py
```

Generate Python and C++ from the same definition with:

```bash
python scripts/generate_protobuf.py --cpp-out generated/cpp
```

For a plain-C embedded target, use a `.proto` compatible C generator such as
nanopb or protobuf-c against the same `schema/urex.proto`; do not duplicate the
packet structure manually in C.

## Generating bindings on Windows

Install the development dependencies from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Generate Python and C++ bindings with protoc 33.5 available on PATH:

```powershell
.\.venv\Scripts\python.exe scripts\generate_protobuf.py --cpp-out generated\cpp
```

Generate plain-C bindings from the same schema with nanopb:

```powershell
New-Item -ItemType Directory -Force generated\c | Out-Null
.\.venv\Scripts\nanopb_generator.exe -I schema -D generated\c schema\urex.proto
```

The generated C++ files require a compatible C++ Protobuf runtime. The
generated C files require nanopb's `pb_common.c`, `pb_encode.c`, and
`pb_decode.c`. Generated bindings encode the Protobuf body only; each
implementation must also handle the UREX frame and CRC.

## Hardware frame around Protobuf

Each transport message contains exactly one frame:

```text
magic "UX" (2 bytes)
frame version (1 byte)
protobuf length (4 bytes, big endian)
serialized urex.UrexPacket (variable length)
CRC-16/CCITT-FALSE (2 bytes, big endian)
```

The CRC covers `magic + frame version + protobuf length + protobuf bytes`.
The receiver validates frame length and CRC before parsing Protobuf.
