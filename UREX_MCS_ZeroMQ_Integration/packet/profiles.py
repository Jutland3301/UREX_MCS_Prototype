"""UREX schema-adjacent GUI/simulator metadata for v0.3.b."""

from common.enums import CANStatus, MessageType, ProcessStatus, RadioState, SDRStatus
from packet.protocol import CRCConfig, FieldSpec, FrameLayout, PacketDefinition, ProtocolProfile


RPI_STATUS = 0x0101
RADIO_STATUS = 0x0201
SDR_STATUS = 0x0301
CAN_STATUS = 0x0401
SPACECRAFT_POWER = 0x0501


def enum_values(enum_type: type) -> tuple[str, ...]:
    return tuple(member.value for member in enum_type)


PROVISIONAL_PROFILE = ProtocolProfile(
    name="UREX Protocol Buffers + CRC v0.3.b",
    protocol_version=1,
    frame=FrameLayout(magic=b"UX", frame_version=1),
    crc=CRCConfig(enabled=True),
    terminator=b"",
    max_message_size=None,
    packet_definitions=(
        PacketDefinition(
            packet_id=RPI_STATUS,
            name="RPI_STATUS",
            protobuf_field="rpi_status",
            source_id=1,
            target="raspberry",
            fields=(
                FieldSpec("uptime_s", "float", "s", minimum=0),
                FieldSpec("cpu_temperature_c", "float", "degC", -100, 200, True),
                FieldSpec("cpu_usage_percent", "float", "%", 0, 100, True),
                FieldSpec("memory_usage_percent", "float", "%", 0, 100, True),
                FieldSpec("disk_usage_percent", "float", "%", 0, 100, True),
                FieldSpec("process_status", "enum", enum_type=ProcessStatus, enum_values=enum_values(ProcessStatus)),
                FieldSpec("restart_count", "int", minimum=0),
                FieldSpec("error_count", "int", minimum=0),
            ),
        ),
        PacketDefinition(
            packet_id=RADIO_STATUS,
            name="RADIO_STATUS",
            protobuf_field="radio_status",
            source_id=2,
            target="radio",
            fields=(
                FieldSpec("state", "enum", enum_type=RadioState, enum_values=enum_values(RadioState)),
                FieldSpec("frequency_hz", "int", "Hz", minimum=0, optional=True),
                FieldSpec("rssi_dbm", "float", "dBm", -200, 100, True),
                FieldSpec("snr_db", "float", "dB", -100, 100, True),
                FieldSpec("tx_power_dbm", "float", "dBm", -100, 100, True),
                FieldSpec("bitrate_bps", "int", "bit/s", minimum=0, optional=True),
                FieldSpec("channel_id", "int", minimum=0, optional=True),
                FieldSpec("rx_packet_count", "int", minimum=0),
                FieldSpec("tx_packet_count", "int", minimum=0),
                FieldSpec("rx_error_count", "int", minimum=0),
                FieldSpec("packet_loss_count", "int", minimum=0),
                FieldSpec("pa_temperature_c", "float", "degC", -100, 200, True),
                FieldSpec("lock_status", "bool", optional=True),
            ),
        ),
        PacketDefinition(
            packet_id=SDR_STATUS,
            name="SDR_STATUS",
            protobuf_field="sdr_status",
            source_id=3,
            target="sdr",
            fields=(
                FieldSpec("status", "enum", enum_type=SDRStatus, enum_values=enum_values(SDRStatus)),
                FieldSpec("center_frequency_hz", "int", "Hz", minimum=0, optional=True),
                FieldSpec("sample_rate_sps", "int", "sample/s", minimum=0, optional=True),
                FieldSpec("bandwidth_hz", "int", "Hz", minimum=0, optional=True),
                FieldSpec("gain_db", "float", "dB", -100, 200, True),
                FieldSpec("rx_sample_count", "int", minimum=0),
                FieldSpec("overrun_count", "int", minimum=0),
                FieldSpec("underrun_count", "int", minimum=0),
                FieldSpec("error_count", "int", minimum=0),
            ),
        ),
        PacketDefinition(
            packet_id=CAN_STATUS,
            name="CAN_STATUS",
            protobuf_field="can_status",
            source_id=4,
            target="can",
            fields=(
                FieldSpec("status", "enum", enum_type=CANStatus, enum_values=enum_values(CANStatus)),
                FieldSpec("bitrate_bps", "int", "bit/s", minimum=0, optional=True),
                FieldSpec("rx_frame_count", "int", minimum=0),
                FieldSpec("tx_frame_count", "int", minimum=0),
                FieldSpec("error_count", "int", minimum=0),
                FieldSpec("bus_off_count", "int", minimum=0),
                FieldSpec("last_rx_id", "int", minimum=0, optional=True),
                FieldSpec("last_tx_id", "int", minimum=0, optional=True),
            ),
        ),
        PacketDefinition(
            packet_id=SPACECRAFT_POWER,
            name="SPACECRAFT_POWER",
            protobuf_field="spacecraft_power",
            source_id=5,
            target="spacecraft",
            fields=(
                FieldSpec("spacecraft_bus_voltage_v", "float", "V", 0, 65, True),
                FieldSpec("spacecraft_bus_current_a", "float", "A", 0, 65, True),
                FieldSpec("battery_temperature_c", "float", "degC", -100, 200, True),
                FieldSpec("battery_state_of_charge_percent", "float", "%", 0, 100, True),
                FieldSpec("obc_state", "enum", enum_values=("NOMINAL", "SAFE", "RECOVERY", "ERROR")),
            ),
        ),
    ),
)
