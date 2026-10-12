"""Shared protocol/data definitions for the UREX Ground System."""

from .enums import (
    MessageType,
    LinkStatus,
    ProcessStatus,
    RadioState,
    SDRStatus,
    CANStatus,
    CRCStatus,
    ParseStatus,
    CommandStatus,
    LogSeverity,
)
from .telemetry import (
    PacketMeta,
    RaspberryTelemetry,
    LinkTelemetry,
    RadioTelemetry,
    SDRTelemetry,
    CANTelemetry,
    SpacecraftTelemetry,
    TelemetryFrame,
)
from .packet import Packet
from .commands import Command, CommandResponse
from .crc import calculate_crc16_ccitt, verify_crc16_ccitt

__all__ = [
    "MessageType",
    "LinkStatus",
    "ProcessStatus",
    "RadioState",
    "SDRStatus",
    "CANStatus",
    "CRCStatus",
    "ParseStatus",
    "CommandStatus",
    "LogSeverity",
    "PacketMeta",
    "RaspberryTelemetry",
    "LinkTelemetry",
    "RadioTelemetry",
    "SDRTelemetry",
    "CANTelemetry",
    "SpacecraftTelemetry",
    "TelemetryFrame",
    "Packet",
    "Command",
    "CommandResponse",
    "calculate_crc16_ccitt",
    "verify_crc16_ccitt",
]
