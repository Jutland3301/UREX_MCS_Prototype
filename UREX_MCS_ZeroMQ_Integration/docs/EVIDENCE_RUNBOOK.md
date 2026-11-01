# Automated H1/H2/H3 evidence collection

Run everything below from `UREX_MCS_ZeroMQ_Integration/` inside branch
`feature/automated-h123-evidence`. The repository-root app is the older simulator.

## What the hardware team does on each collection day

1. Connect the MCS PC and Pi to the same lab network and connect the required radio hardware.
2. Start the configured Pi agent (one command).
3. Start `run_evidence_pc.bat` on Windows, or `sh run_evidence_pc.sh` on Linux.
4. Return the single ZIP printed by the PC runner. No manual cut/reconnect, repeated
   command entry, spreadsheet calculations, or copying Pi logs is required.

The sample plan takes roughly 9–12 minutes plus native-command response time.
Failures/timeouts create explicit BLOCKED/INCOMPLETE/FAIL records and do not prevent
independent later trials. `COMPLETE` means measurement collection completed; it is
not a claim that a research hypothesis is supported. PC exit 0 means complete
collection; exit 2 means partial/failed collection. Always return the ZIP either way.

## One-time setup: the unavoidable hardware-specific information

This repository does not contain the hardware team's native radio driver. We
cannot invent its executable name, launch flags or valid radio commands.
Configure these once; subsequent collection runs need no test-by-test decisions.

- PC and Pi IP addresses (PC must be reachable from the Pi).
- Native Pi service executable and its existing `--connect` equivalent.
- One or more approved, repeatable command payloads and exact expected RX payloads.
  Prefer a read-only status/query command. The checked-in plan deliberately has no
  radio commands. Empty commands produce BLOCKED H3 and command-load trials.
- Native service must use `schema/integration.proto` and the UX+CRC envelope in
  `docs/MCS_PI_INTERFACE.md`. This is not compatible with arbitrary JSON/native
  radio drivers without their existing adapter.

On the **PC**, use Python 3.10+ and install once:

```sh
python -m pip install -r requirements-evidence.txt
```

On the **Pi**, install once (no Qt package is required):

```sh
python3 -m pip install -r requirements-evidence-pi.txt
```

Use a venv if the system Python rejects package installation. Python requirements
include an embedded aMQTT broker, so Mosquitto, sudo and a separately managed broker
are not required. The tested broker is **aMQTT 0.11.4**, not Mosquitto. Results must
name that implementation rather than silently combining them with older results.

Copy `evidence-plan.example.json` to `evidence-plan.local.json` on the PC and fill
`pi_url`, `mcs_host` and `token`. `mcs_bind`/`mcs_port` must name the same PC port.
The local plan is ignored by git; the result ZIP includes a token-redacted copy.
Add H3 steps using actual hardware-approved bytes, e.g. the following **shape**
(values below are placeholders, not valid radio commands):

```json
{"name":"approved status query", "payload_hex":"ACTUAL_HEX",
 "expected_rx_hex":"ACTUAL_RESPONSE_HEX", "delay_s":0.2}
```

H1's command-load phases repeat the first configured command. H3 repeats the
entire configured list. An exact response is matched only after command submission,
with one H3 command outstanding at a time; the raw packet keys/times are recorded.
If the real protocol has dynamic response bytes or requires a native response ID,
configure/extend the matching rule before claiming command→telemetry causality.
No response rule means INCOMPLETE, even if TX_COMPLETED was received.

### Pi startup

Use the same token as the local PC plan. The token protects the control API; use
this on a trusted lab LAN (the control API is HTTP, not TLS).

The agent can start the native executable itself. Supply its real argv as JSON
and use `{endpoint}` for the proxy endpoint. For example, **replace the executable
and flags with the actual hardware team's program**:

```sh
python3 -m evidence_suite.agent --token YOUR_SHARED_TOKEN --native-command '["/actual/path/to/native_service","--connect","{endpoint}"]'
```

Alternatively, start the agent without `--native-command` and configure the
already-running native service to connect to `tcp://127.0.0.1:5558` once:

```sh
python3 -m evidence_suite.agent --token YOUR_SHARED_TOKEN
```

The native service then connects to the local recording proxy, which forwards to
the PC. Existing hardware-provided frames/IDs are preserved; no synthetic radio
success or RSSI/SNR is introduced. The agent terminates only a child process it
started itself. The PC always requests cleanup and Pi artifact recovery at the end.
Sessions also have a one-hour expiry if the PC disappears.

Default connections:

| Destination | Port | Purpose |
|---|---:|---|
| Pi | 8765 | PC control and automatic Pi ZIP download |
| PC | 5557 | Actual MCS integration GUI |
| Pi | 5558 | Native-service recording proxy (native service connects locally) |
| Pi | 5559 | H2 ZeroMQ echo |
| Pi | 18884 | H2 embedded MQTT broker |

Allow the corresponding lab-network firewall connections. Avoid port collisions
with existing services; agent flags and plan fields allow changes. The MQTT broker
and benchmark echo do not expose native radio commands.

## Exactly what each test measures

### H1: native traffic, concurrent commands, GUI and DB

The actual existing GUI stays open. A 20-ms timer records lateness, total tick
cost, and log-write cost; a worker thread orchestrates the test through Qt signals.
Passive and concurrent-command phases repeat automatically. RX rate is **observed**
from real hardware traffic; this runner does not pretend to control the radio's
telemetry generation rate. Configure the real sender separately if controlled
increased-rate radio telemetry is required. No telemetry yields INCOMPLETE.

SQLite records include `run_id` (phase name), native session/sequence, command IDs,
both timestamp fields, RSSI/SNR and latest reported modem configuration summary.
The Pi proxy independently records frames forwarded toward the MCS. Final
reconciliation compares radio-receive session/sequence keys with persisted MCS DB
rows, reporting missing, extra and duplicate rows. A proxy forward is a ZeroMQ
queue-acceptance observation, not proof of RF transmission or reception upstream.

The GUI still polls communication and writes SQLite synchronously on its main
thread. This suite measures that architecture; it does not implement or prove
worker-isolated/multithreaded MCS I/O. Timer lateness is an event-loop responsiveness
proxy, not a human click-to-pixel measurement. Offscreen runs are explicitly marked.

### H2: matched PC↔Pi middleware echo, no radio

Each configured traffic profile is repeated for ZeroMQ DEALER/ROUTER, MQTT 3.1.1
QoS0, and MQTT 3.1.1 QoS1 with persistent sessions. Payload size/rate/duration are
matched. Every payload contains a sequence and the PC monotonic timestamp, enabling
round-trip measurements **without assuming synchronized PC and Pi clocks**.

During every trial the PC intentionally disconnects only its test client, continues
offering messages, then reconnects. Paho QoS1 has a bounded local offline queue;
ZeroMQ IMMEDIATE rejects unavailable sends. Report this configuration when
interpreting recovery. This is an intentional client disconnect, not cable removal,
network packet-loss injection, TCP half-open detection, or inherent protocol
superiority. It does not reproduce the older PUB/SUB benchmark pattern exactly.

Raw sends and echoes record timing, acceptance and phase. Summaries report stable,
outage and post-reconnect RTT distributions; offered/accepted/returned counts;
missing/duplicate/reordered/corrupt echoes; and first fresh-echo recovery time.
RTT must not be labelled as measured one-way latency. Lost echo requests and lost
responses cannot be distinguished from RTT data alone; Pi raw request logs permit
further analysis. No RF claim is made by H2.

### H3: repeated native command scripts

The runner invokes the same MCS `transmit()` path used by the manual GUI button,
waits for terminal command state and the configured RX response, then advances.
It records each sequence execution and the matched packet keys. Timeouts remain
OUTCOME_UNKNOWN, without automatically replaying a command. Repeats are deliberate
new script executions with new command IDs. TX_COMPLETED alone does not pass a
response check. This suite automates operation; a separately performed manual
baseline is not fabricated.

## Returned files

`evidence-results/<suite-UUID>.zip` contains:

- `summary.csv`: flat metrics for Excel; `details_json` preserves full detail.
- `summary.json`: all trials, errors, provenance and cross-machine reconciliation.
- `mcs/*.db` and `mcs/*.jsonl`: actual MCS packet/event logs.
- `mcs-metrics.jsonl`: GUI timer, write timing and phase-labelled event records.
- `pc-resources.jsonl` and Pi `pi-resources.jsonl`: per-process CPU/RSS at one-second intervals, tagged by trial. CPU is one core = 100%; the first sample per process is warm-up. The embedded broker shares the agent process; its CPU is not isolated from the proxy/coordinator.
- `H2-*/samples.jsonl`: per-message raw timing and connection events.
- `pi-evidence.zip`: Pi proxy trace, native child console, middleware echo trace,
  environment/commit/package versions and cleanup state.
- Redacted plan, PC manifest and SHA256 checksums.

SQLite replaces automatic CSV packet logging; JSONL remains an independent readable
copy. DB rows use NULL for unavailable values, preserving actual numeric zero.
Modem configuration is the last reported RADIO configuration summary plus its
Status timestamp/sequence. It is not assumed to be the exact configuration at RF
reception. No old CSV files are migrated automatically.

## Local software validation only

```sh
python -m pip install -r requirements-evidence-pi.txt
python -m pip install -r requirements-evidence.txt
python -m pytest -q
python -m evidence_suite.selftest
```

Selftest launches two separate processes, the real GUI in offscreen mode, a Python
mock backend, actual TCP ZeroMQ, and the embedded MQTT broker. It checks H1/H3,
all three H2 variants, SQLite reconciliation and automatic Pi ZIP retrieval. Every
result is explicitly labelled `MOCK_VALIDATION_ONLY`; it is **not** Pi ARM or radio
hardware evidence. Never pass `--mock` for the final hardware collection.
