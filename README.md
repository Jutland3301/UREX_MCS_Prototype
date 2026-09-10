# UREX Mission Control System Simulator v0.3.b

PySide6 MCS simulator with a **Protocol Buffers packet contract** and a
hardware-facing **CRC-16/CCITT-FALSE** frame.

PySide6 remains the GUI layer. Packet serialization/deserialization is handled
by generated Protocol Buffers message classes, while the UREX frame provides
message length and mandatory application CRC validation.

The telemetry field set and IDs are still provisional until the hardware team
approves the interface. The encoding architecture itself is now designed for
one cross-language schema rather than hand-written Python `struct` layouts.

## Data path

```text
PySide6 / TelemetrySimulator / ManualPacketSource
                    |
                    v
              logical Packet
                    |
                    v
        generated urex_pb2 classes
          SerializeToString()
                    |
                    v
     UREX frame + CRC-16/CCITT-FALSE
                    |
                    v
          transport as raw bytes
                    |
                    v
       frame length + CRC validation
                    |
                    v
           ParseFromString()
                    |
                    v
        TelemetryState -> PySide6 GUI
```

A CRC-failed frame is rejected **before** Protobuf decoding and cannot update
GUI telemetry state.

## One packet definition for multiple languages

The authoritative wire schema is:

```text
schema/urex.proto
```

The current packet payload IDs are represented directly by the Protobuf
`oneof` field numbers:

| Payload | Field / packet ID |
| --- | ---: |
| `rpi_status` | `0x0101` / 257 |
| `radio_status` | `0x0201` / 513 |
| `sdr_status` | `0x0301` / 769 |
| `can_status` | `0x0401` / 1025 |
| `spacecraft_power` | `0x0501` / 1281 |

Python and C++ bindings can therefore be generated from the same `.proto`
instead of maintaining separate packet layouts. For plain C, use a compatible
generator such as nanopb or protobuf-c against the same schema.

## CRC framing

Protobuf provides serialization, not a hardware integrity checksum, so v0.3.b
keeps a deliberately small outer frame:

```text
"UX" magic             2 bytes
frame version           1 byte
protobuf body length    4 bytes, big endian
urex.UrexPacket         variable length
CRC-16/CCITT-FALSE      2 bytes, big endian
```

CRC coverage is the complete frame header plus serialized Protobuf body.
Application CRC is mandatory in the active v0.3.b profile.

## What changed from v0.3-alpha

The previous codec used `FieldSpec.to_wire()`, numeric scaling/sentinels,
`struct.pack()`, a fixed packet header, and matching manual decode logic.
v0.3.b replaces that wire logic with Protocol Buffers. `packet/profiles.py`
now contains only simulator/UI metadata such as units, ranges, source/target,
and update period; it no longer determines primitive byte widths or packet
endianness.

Optional Protobuf scalar fields replace values such as `0xFFFFFFFF` and
`-32768` that previously represented missing telemetry.

## Important files

- `schema/urex.proto` — authoritative language-neutral packet definition
- `packet/generated/urex_pb2.py` — Python Protobuf binding used at runtime
- `scripts/generate_protobuf.py` — compiler entry point for Python/C++ bindings
- `packet/encoder.py` — logical packet -> Protobuf -> CRC frame
- `packet/parser.py` — frame/CRC validation -> Protobuf -> telemetry fields
- `packet/protocol.py` — CRC/frame configuration and GUI metadata models
- `packet/profiles.py` — provisional simulator metadata, not binary packing
- `communication/base_transport.py` — transport-independent raw-byte interface

## Generate Protobuf bindings

Development setup:

```bash
python -m pip install -r requirements-dev.txt
python scripts/generate_protobuf.py
```

To generate C++ at the same time:

```bash
python scripts/generate_protobuf.py --cpp-out generated/cpp
```

The repository includes a Python binding so the simulator can run without
requiring `protoc` at runtime. CI regenerates it from `schema/urex.proto` before
testing.

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

Headless experiment:

```bash
python -m simulator.headless_runner --duration 60 --burst 5 \
  --drop 2 --corrupt 1 --delay 50 --jitter 10 \
  --output results/run.json
```

## Test

```bash
pytest -q
```

v0.3.b adds tests for generated Protobuf serialization, schema-derived packet
IDs, optional-field presence, mandatory CRC, CRC-before-decode rejection,
valid-CRC semantic failures, simulator fault injection, and the existing
transport/experiment behavior.

See `PROTOCOL_ASSUMPTIONS.md` for the remaining hardware questions.

## Windows release build and digital signing

`run.bat` and `setup_and_run.bat` are now **development-only launchers**. Do not
use them as the user-facing release entry point.

Build the Windows release application with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The generated release entry point is:

```text
dist\UREX_MCS_Simulator\UREX_MCS_Simulator.exe
```

Before distribution, sign that executable with the project's Authenticode
code-signing identity:

```powershell
.\scripts\sign_windows.ps1 -CertificateThumbprint "<THUMBPRINT>"
```

The signing script uses SHA-256 plus an RFC 3161 timestamp and verifies the
result after signing. See `docs/WINDOWS_SIGNING.md` for certificate choices,
SmartScreen behavior, and the release procedure.
