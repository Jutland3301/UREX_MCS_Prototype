# Evidence-suite validation — 1 November 2026

Integration base: `v1.0-zeromq-integration`, latest upstream
`3b21835fa3878f8d9dff774577777280ece299bd`.

- `QT_QPA_PLATFORM=offscreen python -m pytest -q`: **49 passed, 3 skipped**.
  The skips are existing C++ mock cases; no C++ compiler/protoc validation is claimed.
- `python -m evidence_suite.selftest`: **PASS**. Separate mock Pi process, actual
  TCP proxy, existing Qt network GUI, SQLite/JSONL, ZeroMQ echo and MQTT QoS0/QoS1
  through aMQTT 0.11.4. Six collections completed (H1 concurrent, H3 twice, three
  H2 middleware variants), automatic Pi ZIP recovery completed, five radio-receive
  mock frames matched five DB records without missing/extra/duplicate records.
- Missing-native-service negative integration: **PASS**. No native Status was
  available; H1/H3 were BLOCKED, independent H2 cases still collected, Pi ZIP was
  recovered, no telemetry was invented, packet reconciliation and overall result
  remained INCOMPLETE (exit 2).
- A passive mock phase with no incoming radio frames correctly produced
  INCOMPLETE rather than claiming a successful full-duplex experiment.

Software validation ran on Linux x86_64/Python 3.12 in an offscreen GUI environment.
No Raspberry Pi ARM execution or physical radio validation was available.
`MOCK_VALIDATION_ONLY` remains attached to every mock selftest result.

The latest upstream manual edits were retained in intent (3-second completion
wait, modem-summary logging, SQLite) while correcting:

- `kind_name` initialization accidentally nested under RSSI/SNR presence;
- `config_state_time_unix_ms` vs `config_status_time_unix_ms` spelling mismatch;
- EventLog shutdown still referencing removed CSV members;
- PiEngine shutdown accidentally using EventLog-only members instead of stopping
  its transport and closing its log.

These code paths are exercised by regression tests and the end-to-end run.
