from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from common.crc import calculate_crc16_ccitt
from common.enums import MessageType


@dataclass(frozen=True)
class CRCConfig:
    """Hardware-facing CRC configuration for the outer UREX frame."""

    enabled: bool = True
    name: str = "CRC-16/CCITT-FALSE"
    width_bytes: int = 2
    byte_order: str = "big"
    coverage: str = "frame_header_and_protobuf"
    calculator: Callable[[bytes], int] = calculate_crc16_ccitt

    def material(self, frame_header: bytes, protobuf_payload: bytes) -> bytes:
        if self.coverage == "frame_header_and_protobuf":
            return frame_header + protobuf_payload
        if self.coverage == "protobuf_only":
            return protobuf_payload
        raise ValueError(f"unsupported CRC coverage: {self.coverage}")


@dataclass(frozen=True)
class FrameHeader:
    magic: bytes
    frame_version: int
    protobuf_length: int


@dataclass(frozen=True)
class FrameLayout:
    """
    Minimal deterministic envelope around Protobuf bytes.

    Protobuf defines the packet/message fields. This envelope only provides
    stream/message framing plus the bytes covered by the hardware CRC.
    Layout: magic[2] | frame_version[1] | protobuf_length[4, big-endian].
    """

    magic: bytes = b"UX"
    frame_version: int = 1
    length_bytes: int = 4
    byte_order: str = "big"

    @property
    def size(self) -> int:
        return len(self.magic) + 1 + self.length_bytes

    def pack(self, protobuf_length: int) -> bytes:
        if not 0 <= self.frame_version <= 0xFF:
            raise ValueError("frame_version must fit in one byte")
        if protobuf_length < 0:
            raise ValueError("protobuf_length must not be negative")
        maximum = (1 << (8 * self.length_bytes)) - 1
        if protobuf_length > maximum:
            raise ValueError("protobuf payload is too large for frame length field")
        return (
            self.magic
            + bytes((self.frame_version,))
            + protobuf_length.to_bytes(self.length_bytes, self.byte_order)
        )

    def unpack(self, data: bytes) -> FrameHeader:
        if len(data) < self.size:
            raise ValueError(f"frame header requires {self.size} bytes")
        magic_end = len(self.magic)
        magic = data[:magic_end]
        frame_version = data[magic_end]
        protobuf_length = int.from_bytes(
            data[magic_end + 1 : self.size],
            self.byte_order,
        )
        return FrameHeader(
            magic=magic,
            frame_version=frame_version,
            protobuf_length=protobuf_length,
        )


@dataclass(frozen=True)
class FieldSpec:
    """GUI/simulator metadata only; no wire width, scale, or byte order lives here."""

    name: str
    value_type: str
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    optional: bool = False
    enum_type: type[Enum] | None = None
    enum_values: tuple[str, ...] = ()

    def validate(self, value: object) -> None:
        if value is None:
            if self.optional:
                return
            raise ValueError(f"{self.name} does not allow a missing value")

        if self.enum_values:
            label = value.value if isinstance(value, Enum) else str(value)
            if label not in self.enum_values:
                raise ValueError(
                    f"unknown {self.name} enum value {label!r}; "
                    f"expected one of {self.enum_values}"
                )
            return

        if self.value_type == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.name} must be boolean")
            return

        if self.value_type == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.name} must be an integer")
            numeric = float(value)
        elif self.value_type == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.name} must be numeric")
            numeric = float(value)
        else:
            raise ValueError(f"unsupported metadata value_type: {self.value_type}")

        if self.minimum is not None and numeric < self.minimum:
            raise ValueError(f"{self.name}={numeric} is below {self.minimum}")
        if self.maximum is not None and numeric > self.maximum:
            raise ValueError(f"{self.name}={numeric} is above {self.maximum}")


@dataclass(frozen=True)
class PacketDefinition:
    packet_id: int
    name: str
    protobuf_field: str
    source_id: int
    target: str
    fields: tuple[FieldSpec, ...]
    update_period_s: float = 1.0
    message_type: MessageType = MessageType.TELEMETRY
    provisional: bool = True


@dataclass(frozen=True)
class ProtocolProfile:
    name: str
    protocol_version: int
    frame: FrameLayout
    crc: CRCConfig
    packet_definitions: tuple[PacketDefinition, ...]
    terminator: bytes = b""
    max_message_size: int | None = None

    def packet_definition(self, packet_id: int) -> PacketDefinition:
        for definition in self.packet_definitions:
            if definition.packet_id == packet_id:
                return definition
        raise KeyError(packet_id)

    def packet_definition_by_protobuf_field(self, protobuf_field: str) -> PacketDefinition:
        for definition in self.packet_definitions:
            if definition.protobuf_field == protobuf_field:
                return definition
        raise KeyError(protobuf_field)

    @property
    def header_size(self) -> int:
        return self.frame.size

    @property
    def crc_size(self) -> int:
        return self.crc.width_bytes if self.crc.enabled else 0
