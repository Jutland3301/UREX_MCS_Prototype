# UREX Mission Control System (MCS) Prototype

Prototype Mission Control System software for UREX.

The current repository establishes the initial MCS software architecture, shared telemetry models, telemetry simulator, and GUI. Hardware communication and packet parsing are intentionally left incomplete until the corresponding interfaces are agreed with the hardware/communications team.

## Current Architecture

```text
Telemetry Simulator
        |
        | TelemetryFrame
        v
      MCS GUI
        |
        +-- System / Connection Status
        +-- Telemetry Display
        +-- Packet Monitor
        +-- Command Panel
        +-- Event / Error Log
```

The simulator currently generates system, RF, SDR, CAN, and spacecraft telemetry and passes it to the GUI through the common `TelemetryFrame` model.

The simulator currently bypasses the communication and packet-processing layers. These layers will later connect external telemetry sources to the same common MCS interfaces.

## Repository Structure

```text
UREX_MCS/
|
+-- common/
|   +-- telemetry.py
|   +-- commands.py
|   +-- packet.py
|   +-- enums.py
|   +-- crc.py
|
+-- simulator/
|   +-- telemetry_simulator.py
|
+-- gui/
|   +-- main_window.py
|
+-- packet/
|   +-- parser.py
|
+-- communication/
|   +-- base_transport.py
|
+-- system_definition_v0.1.txt
+-- README.md
```

### `common/`

Contains shared data structures used across the MCS.

* **`telemetry.py`** - Common telemetry models, including system, Ethernet, RF, SDR, CAN, spacecraft, and packet metadata.
* **`commands.py`** - Command-related data models.
* **`packet.py`** - Common packet representation.
* **`enums.py`** - Shared enumerations and states.
* **`crc.py`** - CRC functionality. Current implementation is provisional until the final packet protocol is defined.

### `simulator/`

**`telemetry_simulator.py`** provides simulated telemetry for MCS development without hardware.

It currently models:

* Raspberry Pi/system health
* Ethernet/link status
* Radio/RF parameters
* SDR state
* CAN state
* Spacecraft power and OBC telemetry
* Time-varying system behaviour
* Fault conditions such as packet loss, CRC errors, link loss, high temperature, low voltage, weak RF, CAN errors/BUS-OFF, and SDR overruns

Simulator output uses the same `TelemetryFrame` model intended for real telemetry.

### `gui/`

**`main_window.py`** implements the current PySide6 MCS GUI prototype.

Current interfaces include:

* System and connection status
* Telemetry monitoring
* Packet monitoring
* Command interface
* Event/error logging

The GUI consumes `TelemetryFrame` objects and is intended to remain independent of whether telemetry originates from the simulator or real hardware.

### `packet/`

**`parser.py`** is reserved for converting incoming raw packets into the common MCS data model.

Implementation is intentionally deferred until packet structure, field widths, byte order, CRC scheme, and related communication details are agreed with the hardware/communications team.

### `communication/`

**`base_transport.py`** is reserved for the transport abstraction between the MCS and external systems.

The final implementation may support transports such as ZeroMQ or MQTT depending on the agreed system architecture.

### `system_definition_v0.1.txt`

Draft MCS system definition covering the intended architecture, telemetry, packet handling, commands, communication, fault handling, and hardware interfaces.

Items marked **TBD** are intentionally unresolved and require further hardware/software integration decisions.

## Next Integration Step

The next major step is to agree on the **packet and communication interfaces** with the hardware/communications team.

Once these interfaces are defined, the packet parser and communication layer can be implemented without changing the existing simulator/GUI telemetry model.
