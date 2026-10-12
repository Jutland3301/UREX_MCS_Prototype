from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.protobuf.message import DecodeError

from common.enums import CRCStatus, MessageType, ParseStatus
from common.telemetry import PacketMeta
from packet.generated import urex_pb2
from packet.protocol import FrameHeader, ProtocolProfile


@dataclass(frozen=True)
class DecodedPacket:
    meta: PacketMeta
    fields: dict[str, object]


@dataclass(frozen=True)
class ParseResult:
    status: ParseStatus
    raw_packet: bytes
    packet: DecodedPacket | None = None
    header: FrameHeader | None = None
    errors: tuple[str, ...] = ()
    application_crc_status: CRCStatus = CRCStatus.NOT_CHECKED

    @property
    def ok(self) -> bool:
        return self.status == ParseStatus.OK and self.packet is not None


class PacketParser:
    """Validate hardware CRC/framing, then decode generated Protocol Buffers."""

    def __init__(self, profile: ProtocolProfile) -> None:
        self.profile = profile

    def parse(self, raw_packet: bytes) -> ParseResult:
        raw_packet = bytes(raw_packet)
        if not raw_packet:
            return self._failure(ParseStatus.EMPTY, raw_packet, "empty message")

        if (
            self.profile.max_message_size is not None
            and len(raw_packet) > self.profile.max_message_size
        ):
            return self._failure(
                ParseStatus.TOO_LARGE,
                raw_packet,
                f"message is {len(raw_packet)} bytes; maximum is "
                f"{self.profile.max_message_size}",
            )

        message = raw_packet
        if self.profile.terminator:
            if not message.endswith(self.profile.terminator):
                return self._failure(
                    ParseStatus.INVALID_LENGTH,
                    raw_packet,
                    "required terminator is missing",
                )
            message = message[: -len(self.profile.terminator)]

        minimum_size = self.profile.header_size + self.profile.crc_size
        if len(message) < minimum_size:
            return self._failure(
                ParseStatus.TOO_SHORT,
                raw_packet,
                f"message is {len(message)} bytes; minimum is {minimum_size}",
            )

        try:
            header = self.profile.frame.unpack(message[: self.profile.header_size])
        except ValueError as exc:
            return self._failure(ParseStatus.INVALID_HEADER, raw_packet, str(exc))

        if header.magic != self.profile.frame.magic:
            return self._failure(
                ParseStatus.INVALID_MAGIC,
                raw_packet,
                f"unexpected magic {header.magic!r}",
                header,
            )
        if header.frame_version != self.profile.frame.frame_version:
            return self._failure(
                ParseStatus.INVALID_HEADER,
                raw_packet,
                f"frame version {header.frame_version} is not supported",
                header,
            )

        expected_length = (
            self.profile.header_size
            + header.protobuf_length
            + self.profile.crc_size
        )
        if len(message) != expected_length:
            return self._failure(
                ParseStatus.INVALID_LENGTH,
                raw_packet,
                f"message is {len(message)} bytes; frame declares {expected_length}",
                header,
            )

        protobuf_start = self.profile.header_size
        protobuf_end = protobuf_start + header.protobuf_length
        protobuf_bytes = message[protobuf_start:protobuf_end]

        if not self.profile.crc.enabled:
            return self._failure(
                ParseStatus.UNSUPPORTED,
                raw_packet,
                "UREX v0.3.b requires application CRC",
                header,
            )

        crc_value = int.from_bytes(
            message[protobuf_end : protobuf_end + self.profile.crc.width_bytes],
            self.profile.crc.byte_order,
        )
        calculated = self.profile.crc.calculator(
            self.profile.crc.material(message[:protobuf_start], protobuf_bytes)
        )
        if calculated != crc_value:
            return self._failure(
                ParseStatus.INVALID_CRC,
                raw_packet,
                f"CRC is 0x{crc_value:04X}; expected 0x{calculated:04X}",
                header,
                CRCStatus.FAIL,
            )

        proto = urex_pb2.UrexPacket()
        try:
            proto.ParseFromString(protobuf_bytes)
        except DecodeError as exc:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                f"invalid protobuf payload: {exc}",
                header,
                CRCStatus.OK,
            )

        if proto.protocol_version != self.profile.protocol_version:
            return self._failure(
                ParseStatus.UNSUPPORTED_VERSION,
                raw_packet,
                f"protocol version {proto.protocol_version} is not supported",
                header,
                CRCStatus.OK,
            )

        try:
            message_type_name = urex_pb2.MessageType.Name(proto.message_type)
            message_type = MessageType(message_type_name)
        except (ValueError, KeyError):
            return self._failure(
                ParseStatus.UNKNOWN_MESSAGE_TYPE,
                raw_packet,
                f"unknown message type code {proto.message_type}",
                header,
                CRCStatus.OK,
            )

        payload_name = proto.WhichOneof("payload")
        if payload_name is None:
            return self._failure(
                ParseStatus.UNKNOWN_PACKET_ID,
                raw_packet,
                "protobuf packet contains no payload",
                header,
                CRCStatus.OK,
            )

        packet_id = proto.DESCRIPTOR.fields_by_name[payload_name].number
        try:
            definition = self.profile.packet_definition(packet_id)
        except KeyError:
            return self._failure(
                ParseStatus.UNKNOWN_PACKET_ID,
                raw_packet,
                f"unknown protobuf payload field number 0x{packet_id:04X}",
                header,
                CRCStatus.OK,
            )

        if definition.protobuf_field != payload_name:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                f"packet ID 0x{packet_id:04X} is mapped to unexpected payload {payload_name}",
                header,
                CRCStatus.OK,
            )
        if message_type != definition.message_type:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                f"packet {definition.name} cannot use {message_type.value}",
                header,
                CRCStatus.OK,
            )
        if proto.source_id != definition.source_id:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                f"packet {definition.name} cannot use source_id={proto.source_id}",
                header,
                CRCStatus.OK,
            )

        payload_message = getattr(proto, payload_name)
        fields: dict[str, object] = {}
        try:
            for field in definition.fields:
                proto_field = payload_message.DESCRIPTOR.fields_by_name[field.name]
                if field.optional and proto_field.has_presence and not payload_message.HasField(field.name):
                    fields[field.name] = None
                    continue

                value = getattr(payload_message, field.name)
                if proto_field.enum_type is not None:
                    enum_value = proto_field.enum_type.values_by_number[int(value)].name
                    if field.enum_type is not None:
                        value = field.enum_type(enum_value)
                    else:
                        value = enum_value
                field.validate(value)
                fields[field.name] = value
        except (KeyError, ValueError) as exc:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                str(exc),
                header,
                CRCStatus.OK,
            )

        try:
            timestamp = datetime.fromtimestamp(proto.timestamp_ms / 1000.0, timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            return self._failure(
                ParseStatus.INVALID_FIELD,
                raw_packet,
                f"invalid timestamp: {exc}",
                header,
                CRCStatus.OK,
            )

        meta = PacketMeta(
            protocol_version=proto.protocol_version,
            message_type=message_type,
            source_id=proto.source_id,
            destination_id=proto.destination_id,
            packet_id=packet_id,
            sequence_number=proto.sequence_number,
            timestamp=timestamp,
            payload_length=payload_message.ByteSize(),
            total_length=len(raw_packet),
            application_crc_value=crc_value,
            application_crc_status=CRCStatus.OK,
            parse_status=ParseStatus.OK,
        )
        packet = DecodedPacket(meta=meta, fields=fields)
        return ParseResult(
            status=ParseStatus.OK,
            raw_packet=raw_packet,
            packet=packet,
            header=header,
            application_crc_status=CRCStatus.OK,
        )

    @staticmethod
    def _failure(
        status: ParseStatus,
        raw_packet: bytes,
        error: str,
        header: FrameHeader | None = None,
        crc_status: CRCStatus = CRCStatus.NOT_CHECKED,
    ) -> ParseResult:
        return ParseResult(
            status=status,
            raw_packet=raw_packet,
            header=header,
            errors=(error,),
            application_crc_status=crc_status,
        )
