"""Integration-only schema inside the existing UX/length/CRC envelope."""
from __future__ import annotations

import math
import struct
import time
from uuid import UUID, uuid4

from google.protobuf.message import DecodeError

from common.crc import calculate_crc16_ccitt
from packet.generated import integration_pb2 as pb

MAX_BODY = 65_536
HEADER = struct.Struct("!2sBI")
PI_BODIES = {"status", "radio_receive", "command_result"}


def _uuid(value: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid UUID") from exc


def validate(packet: pb.IntegrationPacket) -> str:
    if packet.schema_version != 1 or not packet.sequence or not packet.timestamp_unix_ms:
        raise ValueError("invalid schema version, sequence or timestamp")
    _uuid(packet.session_id)
    kind = packet.WhichOneof("body")
    if kind is None:
        raise ValueError("missing or unsupported message body")
    body = getattr(packet, kind)
    if kind == "transmit_request":
        _uuid(body.command_id)
        if not body.payload:
            raise ValueError("empty transmit payload")
    elif kind == "command_result":
        _uuid(body.command_id)
        if body.state not in (pb.ACCEPTED, pb.TX_COMPLETED, pb.FAILED, pb.REJECTED):
            raise ValueError("unsupported command state")
        if body.state in (pb.FAILED, pb.REJECTED) and not body.error_code:
            raise ValueError("failure needs an error code")
        if body.state in (pb.ACCEPTED, pb.TX_COMPLETED) and (body.error_code or body.error_message):
            raise ValueError("successful result contains error details")
    elif kind == "radio_receive":
        if not body.payload:
            raise ValueError("empty receive payload")
        for field in ("rssi_dbm", "snr_db"):
            if body.HasField(field) and not math.isfinite(getattr(body, field)):
                raise ValueError("non-finite radio measurement")
        if body.HasField("radio_crc_ok") and not body.radio_crc_ok:
            raise ValueError("CRC-failed native reception is not successful RX")
        if body.HasField("modem_config"):
            for field in ("frequency_hz", "spreading_factor", "bandwidth_hz"):
                if body.modem_config.HasField(field) and not 0 < getattr(body.modem_config, field) <= 2**63-1:
                    raise ValueError("reported modem configuration must use positive numeric values")
    elif kind == "status":
        if not 1 <= body.max_tx_payload_bytes <= MAX_BODY:
            raise ValueError("invalid hardware TX limit")
        if sorted(c.component for c in body.components) != [1, 2, 3, 4, 5]:
            raise ValueError("status must contain each of the five components once")
        if any(c.health not in (pb.INITIALIZING, pb.READY, pb.DEGRADED, pb.ERROR, pb.UNAVAILABLE)
               for c in body.components):
            raise ValueError("unsupported component health")
    return kind


def encode(packet: pb.IntegrationPacket) -> bytes:
    validate(packet)
    body = packet.SerializeToString(deterministic=True)
    if not 0 < len(body) <= MAX_BODY:
        raise ValueError("integration body exceeds 64 KiB")
    data = HEADER.pack(b"UX", 1, len(body)) + body
    return data + calculate_crc16_ccitt(data).to_bytes(2, "big")


def decode(frame: bytes) -> pb.IntegrationPacket:
    if len(frame) < 10:
        raise ValueError("truncated frame")
    magic, version, length = HEADER.unpack_from(frame)
    if magic != b"UX" or version != 1:
        raise ValueError("bad magic or frame version")
    if not 0 < length <= MAX_BODY or len(frame) != length + 9:
        raise ValueError("invalid frame length")
    if calculate_crc16_ccitt(frame[:-2]) != int.from_bytes(frame[-2:], "big"):
        raise ValueError("bad CRC")
    packet = pb.IntegrationPacket()
    try:
        packet.ParseFromString(frame[7:-2])
    except DecodeError as exc:
        raise ValueError("malformed Protobuf") from exc
    validate(packet)
    return packet


class PacketFactory:
    def __init__(self) -> None:
        self.session_id = str(uuid4())
        self.sequence = 0

    def make(self, kind: str, body, *, timestamp_ms: int | None = None) -> pb.IntegrationPacket:
        self.sequence += 1
        packet = pb.IntegrationPacket(schema_version=1, session_id=self.session_id,
                                      sequence=self.sequence,
                                      timestamp_unix_ms=timestamp_ms if timestamp_ms is not None
                                      else time.time_ns() // 1_000_000)
        getattr(packet, kind).CopyFrom(body)
        validate(packet)
        return packet
