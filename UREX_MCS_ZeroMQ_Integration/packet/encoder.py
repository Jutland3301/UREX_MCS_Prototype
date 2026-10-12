from __future__ import annotations

from enum import Enum

from common.packet import Packet
from packet.generated import urex_pb2
from packet.protocol import ProtocolProfile


class PacketEncoder:
    """Encode logical packets using generated Protocol Buffers bindings + CRC frame."""

    def __init__(self, profile: ProtocolProfile) -> None:
        self.profile = profile

    def encode(self, packet: Packet) -> bytes:
        definition = self.profile.packet_definition(packet.packet_id)
        if packet.message_type != definition.message_type:
            raise ValueError(
                f"{definition.name} requires message type {definition.message_type.value}"
            )
        if packet.source_id != definition.source_id:
            raise ValueError(
                f"{definition.name} requires source_id={definition.source_id}"
            )

        expected_fields = {field.name for field in definition.fields}
        missing = expected_fields.difference(packet.payload)
        if missing:
            raise ValueError(
                f"missing payload fields for {definition.name}: {sorted(missing)}"
            )
        unknown = set(packet.payload).difference(expected_fields)
        if unknown:
            raise ValueError(
                f"unknown payload fields for {definition.name}: {sorted(unknown)}"
            )

        proto = urex_pb2.UrexPacket()
        proto.protocol_version = int(packet.protocol_version)
        try:
            proto.message_type = urex_pb2.MessageType.Value(packet.message_type.value)
        except ValueError as exc:
            raise ValueError(f"unsupported message type: {packet.message_type}") from exc
        proto.source_id = int(packet.source_id)
        proto.destination_id = int(packet.destination_id)
        proto.flags = int(packet.flags)
        proto.sequence_number = int(packet.sequence_number)
        proto.timestamp_ms = int(packet.timestamp.timestamp() * 1000)

        payload_message = getattr(proto, definition.protobuf_field)
        for field in definition.fields:
            value = packet.payload[field.name]
            field.validate(value)
            if value is None:
                continue

            proto_field = payload_message.DESCRIPTOR.fields_by_name[field.name]
            if proto_field.enum_type is not None:
                label = value.value if isinstance(value, Enum) else str(value)
                try:
                    wire_value = proto_field.enum_type.values_by_name[label].number
                except KeyError as exc:
                    raise ValueError(
                        f"{definition.name}.{field.name} has no protobuf enum value {label!r}"
                    ) from exc
                setattr(payload_message, field.name, wire_value)
            else:
                setattr(payload_message, field.name, value)

        protobuf_bytes = proto.SerializeToString(deterministic=True)
        frame_header = self.profile.frame.pack(len(protobuf_bytes))
        encoded = frame_header + protobuf_bytes

        if not self.profile.crc.enabled:
            raise ValueError("UREX v0.3.b requires application CRC for hardware packets")

        crc_value = self.profile.crc.calculator(
            self.profile.crc.material(frame_header, protobuf_bytes)
        )
        encoded += crc_value.to_bytes(
            self.profile.crc.width_bytes,
            self.profile.crc.byte_order,
        )
        encoded += self.profile.terminator

        if (
            self.profile.max_message_size is not None
            and len(encoded) > self.profile.max_message_size
        ):
            raise ValueError(
                f"encoded message is {len(encoded)} bytes; maximum is "
                f"{self.profile.max_message_size}"
            )
        return encoded
