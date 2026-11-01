# Completion timeout update — 1 November 2026

Base: v1.0-zeromq-integration, commit 574a1728580f838cfd326d6994c636c16bff75f2.

The default MCS completion timeout is now 3 seconds after ACCEPTED (previously 10).
The separate acceptance timeout remains 2 seconds. No automatic retransmission
is performed. Expiry yields OUTCOME_UNKNOWN; a late valid completion resolves it.
The deadline is evaluated by the GUI polling loop, so display updates occur on
the next tick rather than at an exact real-time deadline.

## Validation

Command: QT_QPA_PLATFORM=offscreen python -m pytest -q
Result: 41 passed, 3 skipped (2.01 s).
New deterministic clock tests cover completion at 2.9 seconds, no completion at
the 3-second boundary, and a completion arriving at 3.2 seconds. All three also
check that the MCS sends only the original request, without automatic replay.
Existing Python TCP process and offscreen GUI checks passed.

Three C++ mock cases were skipped because the compiled binary is unavailable.
The C++ build could not run because protoc is absent from this environment.
These are software tests; no physical Pi/radio validation was performed.

## Run

Extract the archive and run setup_and_run.bat for dependencies if needed.
For the network integration GUI, open a terminal in the extracted directory:

    python main.py --network

Use the existing endpoint configuration for your Pi. This archive changes only
the timeout default, its documentation, and regression tests. It does not
include subsequent hardware-team changes outside the GitHub base above.
