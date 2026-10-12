# Integration validation — 12 October 2026

Base: GitHub `Jutland3301/UREX_MCS_Prototype`, v1.0 at `5a7664146af0caaf6ee69387ec9c7864d8db0eb4`.

## Environment and method

Linux x86_64, Python 3.12, PyZMQ 27.2.0 / libzmq 4.3.5, Python Protobuf 6.33.6,
PySide6 6.12.0. C++ service compiled with g++ using Protobuf compiler/runtime
3.21.12 and libzmq 4.3.5. C++ bindings were generated from the same
`schema/integration.proto`, rather than reusing Python bindings.

Tests use real TCP, with separate Python or compiled C++ mock processes.
The runner denies interface enumeration for a loopback-specific ZeroMQ bind;
wildcard TCP bind with a loopback connecting peer works and is used for these
checks. This does not replace transport with an in-memory fake.

## Results

`python -m pytest -q`: **41 passed** — 23 existing simulator tests plus 18
integration tests/parameter cases, including C++ process checks.

| Check | Result |
|---|---|
| Existing packet/simulator regressions | Pass |
| Shared 94-byte frame, body length 85, CRC 0x87F0 | Pass |
| Bad CRC, length, version, magic, truncation, oversize rejection | Pass |
| Absent RSSI/SNR, non-finite measurements, native failed CRC handling | Pass |
| Hardware not ready, payload limit, duplicate ID and ID conflict | Pass |
| Timeout remains unknown; late completion can resolve it | Pass |
| Pi session change, retired session rejection, RX duplicate suppression | Pass |
| CSV and JSONL preserve binary bytes and absent measurements | Pass |
| Python mock over TCP: success, fail, timeout, restart and duplicate request | Pass |
| Compiled C++ mock over TCP: success, fail, timeout, restart and duplicate request | Pass |
| Qt network monitor: Status, binary TX, completion, RX display | Pass |
| Original simulator and network GUI offscreen startup/shutdown | Pass |

The C++ compiler completed with `-Wall -Wextra` without warnings. A rendered
network window was inspected; status and command columns were widened so command
states and IDs are readable.

## Reproduction

```bash
python -m pip install -r requirements-dev.txt
make -C pi_service
python -m pytest -q
python main.py --smoke-test
python main.py --network --smoke-test --bind "tcp://*:15557"
```

Without the C++ build, three cross-language parameter cases are explicitly
skipped. Python/GUI/legacy tests still run; a skip is not evidence of a C++ pass.
C++ build artifacts are deliberately excluded from the source archive; build on
the target Pi so libraries and CPU architecture match its environment.

## Remaining physical integration

No native RadioLib, SPI/GPIO or ESP32 UART driver is included or tested. The
hardware team's existing C++ source has not been provided. Native TX completion,
effective binary payload capacity, RX/CRC API, initialization recovery and worker
queues must be connected and verified with that source. Raspberry Pi ARM build,
the real LR2021→LR1121 link, full-duplex behavior and real hardware timing are not
claimed by mock-process results. No MQTT/ZeroMQ performance comparison is included.
