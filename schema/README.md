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
