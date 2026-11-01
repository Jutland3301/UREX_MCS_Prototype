# Worker and RX modem settings update — 1 November 2026

Base: automated evidence commit `483a835` (including SQLite and 3-second timeout).

- `integration/worker.py`: QThread creates and owns the network socket, controller
  and SQLite connection. UI commands are nonblocking and UUID-tagged; all worker
  requests are ordered. UI receives copied snapshots/event batches, not live worker
  objects. Display refresh is throttled independently of network polling.
- `QUEUED` is a local GUI state, not a new wire protocol command state.
- Worker-phase flush acknowledgements and final shutdown draining preserve evidence
  batches and DB writes. Socket/SQLite creation, access and close use one worker.
- Evidence profiling observes actual worker write duration and records worker
  thread ID; the GUI timer measures only GUI scheduling/rendering.
- Additive `RadioReceive.modem_config` carries an RX-time settings snapshot. Both
  Python and C++ adapter/service boundaries now support it. Unknown/legacy data is
  explicitly labelled and is not passed off as RX-time configuration.
- The approximately 2.4-second PC/Pi timestamp difference remains **unresolved**;
  this patch neither subtracts a fixed offset nor claims its cause has been fixed.

Validation: 53 Python tests passed, 3 existing C++ process cases skipped. A delayed
250-ms DB/log-write test confirms that GUI timer callbacks continue on the main
thread; thread ownership and close/drain behavior are checked. Per-event settings
round-trip to SQLite/JSONL, remain stable after later modem changes, and override
only the Status fallback for that event. Missing/partial/empty and invalid settings
are covered. Full evidence selftest (real TCP, offscreen GUI, mock native service,
ZeroMQ/MQTT and automatic Pi ZIP recovery) completed successfully. This is software
validation, not Raspberry Pi ARM or RF hardware validation. The updated C++ adapter
source has not been compiled in this environment; the hardware team must rebuild
its native target against the updated schema and populate real RX settings.
