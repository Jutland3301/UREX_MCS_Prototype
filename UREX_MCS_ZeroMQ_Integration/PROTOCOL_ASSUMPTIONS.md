# UREX v0.3.b protocol assumptions and replacement points

Status: Protocol Buffers + mandatory application CRC prototype; final hardware
field/schema approval remains pending.

## Confirmed for this branch

- Pi/MCS application packets require CRC on the hardware side.
- PySide6 is treated only as the GUI/application framework, not as the packet
  serialization contract.
- The project should have one language-neutral packet definition that can be
  compiled into bindings for different implementations.

## v0.3.b architecture decision

`schema/urex.proto` is the authoritative serialization schema. The Python MCS
uses generated Protobuf message classes. A C++ implementation can generate its
classes from the same schema; a plain-C implementation should use a compatible
`.proto` generator such as nanopb/protobuf-c rather than reimplementing the
packet layout independently.

Protobuf does not replace CRC or framing. Each transport message is:

```text
magic[2] | frame_version[1] | protobuf_length[4] | protobuf bytes | crc16[2]
```

The CRC is CRC-16/CCITT-FALSE and covers the frame header plus Protobuf bytes.
The parser validates the declared length and CRC before calling Protobuf
`ParseFromString()`.

## What is no longer part of the packet architecture

The v0.3-alpha packet codec manually specified:

- primitive wire widths (`u8`, `i16`, `u32`, etc.);
- engineering-value scaling before `struct.pack()`;
- numeric sentinel values for missing fields;
- a packet-level byte-order switch;
- manual per-packet `pack`/`unpack` field order.

Those responsibilities are removed from `packet/profiles.py`. Field metadata in
that file now exists only for simulator/GUI validation and display.

## Still provisional

- Exact telemetry/command field list and final packet IDs.
- Exact source/destination identifiers.
- Whether the current five status messages should remain separate.
- Final update periods.
- Maximum Pi-to-MCS application-message size.
- Whether a terminator exists above the transport layer.
- Final CRC polynomial/initialization parameters if hardware specifies a CRC
  variant different from the current CRC-16/CCITT-FALSE prototype.

The reported "63 message bytes + 1 terminator" is still **not** enforced as a
Pi-to-MCS message limit. Protobuf messages are variable-length, and at least one
current v0.3.b test packet exceeds 64 bytes after framing + CRC. That must be
resolved against the actual hardware-interface limit rather than hidden by the
codec.

## Single-definition rule

Packet structure changes should be made in `schema/urex.proto` first and then
regenerated. Do not add a second Python or C/C++ struct definition containing
the same wire fields.

`packet/profiles.py` may still contain non-wire application metadata such as
engineering units, acceptable GUI ranges, target telemetry object, and update
period. Those values can later move into custom Protobuf options if the team
wants the `.proto` to become the single source for UI metadata as well.

## Remaining hardware questions

1. Is the application CRC specifically CRC-16/CCITT-FALSE? If not, provide the
   exact CRC width, polynomial, initial value, reflection rules, XOR-out,
   byte order, and coverage.
2. Does the 63+1 report apply to the native radio frame or final Pi-to-MCS
   Ethernet message?
3. Is a terminator required by the Pi-to-MCS protocol? If yes, what byte(s)?
4. What fields, types, units, ranges, and update rates are actually produced by
   radio, SDR, CAN, Pi, and spacecraft interfaces?
5. Should Pi send each update immediately or periodic snapshots?
6. Which target is plain C versus C++? This determines whether the team should
   standardize on official C++ Protobuf generation or an embedded-C generator.
