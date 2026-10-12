## ZeroMQ integration branch

This branch adds the network interface on top of the v1.0 simulator. It includes
four integration messages, a network monitor with CSV/JSONL logs, Python/C++ mock
Pi services, and a reusable C++ network service. Native RadioLib/TX/RX worker
integration is pending receipt of the hardware team's source. No MQTT comparison
or benchmark code is included.

```bash
python -m pip install -r requirements.txt
python main.py --network --bind "tcp://*:5557"
# In a second terminal:
python -m integration.mock_pi --connect tcp://127.0.0.1:5557
```

Use Hex mode and send `00 0A FF` for a synthetic binary round trip. Start without
`--network` for the original simulator. C++ reference: `make -C pi_service`, then
`./pi_service/build/mock_pi_cpp --connect tcp://127.0.0.1:5557`.

See [the integration guide](docs/INTEGRATION_GUIDE.md),
[the full interface](docs/MCS_PI_INTERFACE.md), and
[validation evidence](docs/INTEGRATION_VALIDATION.md).

### Original v1.0 scope boundary

Version 1.0 is a simulator release. It validates the MCS packet pipeline and GUI behavior using generated packets and simulated transport conditions.

MQTT and ZeroMQ transport comparison is not included in the original simulator or this integration branch.

The simulator does not model satellite-channel packet contamination or perform signal recovery. Its fault injection represents equipment-side hardware faults and simulated transport impairments separately.

## Running from source

~~~text
py -3 main.py --version
py -3 main.py
~~~

Expected version output:

~~~text
UREX MCS Simulator v1.0
~~~

Install dependencies:

~~~text
py -3 -m pip install -r requirements.txt
~~~

Run tests:

~~~text
py -3 -m pytest -q
~~~

## Protocol definition

The authoritative packet definition is:

~~~text
schema/urex.proto
~~~

Generate Python bindings with:

~~~text
py -3 scripts/generate_protobuf.py
~~~

C++ and nanopb bindings can also be generated when the corresponding Protocol Buffers tools are installed.
