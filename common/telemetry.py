from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import (
    MessageType,
    LinkStatus,
    ProcessStatus,
    RadioState,
    SDRStatus,
    CANStatus,
    CRCStatus,
    ParseStatus,
)


@dataclass
class PacketMeta:
    protocol_version: int = 1
    message_type: MessageType = MessageType.TELEMETRY
    source_id: int = 0
    destination_id: int = 0
    packet_id: int = 0
    sequence_number: int = 0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload_length: int = 0
    crc_value: int | None = None
    crc_status: CRCStatus = CRCStatus.NOT_CHECKED
    parse_status: ParseStatus = ParseStatus.OK


@dataclass
class RaspberryTelemetry:
    uptime_s: float = 0.0
    cpu_temperature_c: float | None = None
    cpu_usage_percent: float | None = None
    memory_usage_percent: float | None = None
    memory_used_bytes: int | None = None
    disk_usage_percent: float | None = None
    network_status: LinkStatus = LinkStatus.UNKNOWN
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    process_status: ProcessStatus = ProcessStatus.STARTING
    software_version: str = "0.1.0"
    restart_count: int = 0
    error_count: int = 0
    last_error_code: str | None = None


@dataclass
class LinkTelemetry:
    status: LinkStatus = LinkStatus.DISCONNECTED
    last_rx_timestamp: datetime | None = None
    last_tx_timestamp: datetime | None = None
    rx_message_count: int = 0
    tx_message_count: int = 0
    rx_error_count: int = 0
    tx_error_count: int = 0
    reconnect_count: int = 0
    round_trip_latency_ms: float | None = None
    heartbeat_ok: bool = False
    heartbeat_age_ms: int | None = None


@dataclass
class RadioTelemetry:
    state: RadioState = RadioState.UNKNOWN
    frequency_hz: int | None = None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    tx_power_dbm: float | None = None
    bitrate_bps: int | None = None
    channel_id: int | str | None = None
    modulation: str | None = None
    rx_packet_count: int = 0
    tx_packet_count: int = 0
    rx_error_count: int = 0
    packet_loss_count: int = 0
    pa_temperature_c: float | None = None
    lock_status: bool | None = None
    last_rx_timestamp: datetime | None = None


@dataclass
class SDRTelemetry:
    status: SDRStatus = SDRStatus.OFFLINE
    center_frequency_hz: int | None = None
    sample_rate_sps: int | None = None
    bandwidth_hz: int | None = None
    gain_db: float | None = None
    rx_sample_count: int = 0
    overrun_count: int = 0
    underrun_count: int = 0
    error_count: int = 0


@dataclass
class CANTelemetry:
    status: CANStatus = CANStatus.UNKNOWN
    bitrate_bps: int | None = None
    rx_frame_count: int = 0
    tx_frame_count: int = 0
    error_count: int = 0
    bus_off_count: int = 0
    last_rx_id: int | None = None
    last_tx_id: int | None = None
    last_rx_timestamp: datetime | None = None
    last_error_code: str | None = None


@dataclass
class SpacecraftTelemetry:
    # Intentionally generic until actual spacecraft packet/interface
    # definitions are agreed by the team.
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class TelemetryFrame:
    meta: PacketMeta = field(default_factory=PacketMeta)
    raspberry: RaspberryTelemetry = field(default_factory=RaspberryTelemetry)
    link: LinkTelemetry = field(default_factory=LinkTelemetry)
    radio: RadioTelemetry = field(default_factory=RadioTelemetry)
    sdr: SDRTelemetry = field(default_factory=SDRTelemetry)
    can: CANTelemetry = field(default_factory=CANTelemetry)
    spacecraft: SpacecraftTelemetry = field(default_factory=SpacecraftTelemetry)
    raw_packet: bytes = b""
