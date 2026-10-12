# Changelog

## 0.3.b - 2026-09-10

- Replaced the hand-written packed-binary payload codec with Protocol Buffers.
- Added `schema/urex.proto` as the language-neutral packet contract.
- Added generated Python Protobuf bindings and compiler automation.
- Added a minimal UREX frame around Protobuf with mandatory CRC-16/CCITT-FALSE.
- Validate frame length and CRC before Protobuf parsing.
- Mapped existing packet IDs to Protobuf `oneof` field numbers.
- Replaced missing-value numeric sentinels with Protobuf optional-field presence.
- Removed packet-level byte-order and primitive-width configuration from the profile.
- Kept PySide6, transports, telemetry merge, simulator controls, and experiment flow
  independent of the new serialization implementation.
- Added compiler/test CI and Protobuf/CRC integration tests.
- Added a Windows PyInstaller release bundle and Authenticode signing/verification scripts.
- Demoted BAT launchers to development-only use; release users launch the signed EXE.
- Added an offscreen smoke-test mode for validating the frozen Windows executable.

## 0.3.0-alpha - 2026-09-05

- Added editable engineering-unit values for every provisional packet field.
- Added per-packet update-period controls and repeatable JSON scenarios.
- Added raw hexadecimal packet injection.
- Added configurable packet loss, corruption, fixed delay, and delay jitter.
- Added timed Start/Pause/Resume/Stop experiments and burst-load generation.
- Added live packet, byte-rate, packet-size, delay, and parser-result metrics.
- Added JSON/CSV result export and a GUI-independent headless runner.
- Added tests for manual values, scenario persistence, impairment, scheduling,
  timed experiments, and measurement.
- Kept all Patrick-dependent wire assumptions isolated in the protocol profile.

## 0.2.0 - 2026-09-03

- Added profile-driven packed-binary packet encoding and parsing.
- Added header, length, packet ID, source, field, CRC, and version validation.
- Added partial telemetry state merging and staleness tracking.
- Routed simulator telemetry through raw bytes and a transport adapter.
- Changed parser/CRC fault injection to corrupt real encoded messages.
- Added actual packet lengths and raw hexadecimal data to the packet monitor.
- Separated native/source CRC status from Pi-to-MCS application CRC status.
- Added provisional golden-vector and negative parser tests.
- Isolated all unconfirmed hardware values in `packet/profiles.py`.
- Documented unresolved Patrick/Yucheng interface questions without treating
  the tentative 63+1 report as the MCS packet limit.
