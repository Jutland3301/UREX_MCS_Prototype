### Scope boundary

Version 1.0 is a simulator release. It validates the MCS packet pipeline and GUI behavior using generated packets and simulated transport conditions.

MQTT and ZeroMQ transport comparison is not included in this release. These transports are reserved for a future hardware-integration version.

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