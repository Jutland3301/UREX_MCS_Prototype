from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from common.enums import (
    CANStatus,
    CRCStatus,
    LinkStatus,
    MessageType,
    ParseStatus,
    ProcessStatus,
    RadioState,
    SDRStatus,
)
from common.telemetry import (
    CANTelemetry,
    LinkTelemetry,
    PacketMeta,
    RadioTelemetry,
    RaspberryTelemetry,
    SDRTelemetry,
    SpacecraftTelemetry,
    TelemetryFrame,
)


class TelemetrySimulator:
    """
    Stateful simulator for MCS development.

    Goals:
    - Produce slowly varying telemetry instead of unrelated random values.
    - Return the same TelemetryFrame model that real packet processing will use.
    - Support deliberate fault injection.
    - Avoid embedding GUI-specific behaviour.
    """

    def __init__(self, update_period_s: float = 1.0) -> None:
        self.update_period_s = update_period_s
        self.start_monotonic = time.monotonic()

        self.sequence_number = 0
        self.packet_receive_count = 0
        self.packet_drop_count = 0
        self.packet_crc_error_count = 0
        self.packet_parse_error_count = 0

        # Raspberry Pi state
        self.rpi_cpu_temperature_c = 48.0
        self.rpi_cpu_usage_percent = 18.0
        self.rpi_memory_usage_percent = 32.0
        self.rpi_memory_used_bytes = 650 * 1024 * 1024
        self.rpi_disk_usage_percent = 21.0

        # MCS/RPi communication state
        self.link_status = LinkStatus.CONNECTED
        self.link_rx_message_count = 0
        self.link_tx_message_count = 0
        self.link_rx_error_count = 0
        self.link_tx_error_count = 0
        self.link_reconnect_count = 0
        self.round_trip_latency_ms = 8.0
        self.heartbeat_ok = True
        self.last_rx_timestamp: datetime | None = None
        self.last_tx_timestamp: datetime | None = None

        # Radio state
        self.radio_state = RadioState.RX
        self.radio_frequency_hz = 437_000_000
        self.radio_rssi_dbm = -67.0
        self.radio_snr_db = 12.0
        self.radio_tx_power_dbm = 20.0
        self.radio_bitrate_bps = 9_600
        self.radio_channel_id = 1
        self.radio_modulation = "TBD"
        self.radio_rx_packet_count = 0
        self.radio_tx_packet_count = 0
        self.radio_rx_error_count = 0
        self.radio_packet_loss_count = 0
        self.radio_pa_temperature_c = 42.0
        self.radio_lock_status = True
        self.radio_last_rx_timestamp: datetime | None = None

        # SDR state
        self.sdr_status = SDRStatus.RECEIVING
        self.sdr_center_frequency_hz = 437_000_000
        self.sdr_sample_rate_sps = 1_000_000
        self.sdr_bandwidth_hz = 200_000
        self.sdr_gain_db = 20.0
        self.sdr_rx_sample_count = 0
        self.sdr_overrun_count = 0
        self.sdr_underrun_count = 0
        self.sdr_error_count = 0

        # CAN state
        self.can_status = CANStatus.UP
        self.can_bitrate_bps = 500_000
        self.can_rx_frame_count = 0
        self.can_tx_frame_count = 0
        self.can_error_count = 0
        self.can_bus_off_count = 0
        self.can_last_rx_id: int | None = None
        self.can_last_tx_id: int | None = None
        self.can_last_rx_timestamp: datetime | None = None
        self.can_last_error_code: str | None = None

        # Placeholder spacecraft values.
        # Exact names/parameters remain TBD until team interface definition.
        self.spacecraft_parameters: dict[str, float | int | str | bool] = {
            "spacecraft_bus_voltage_v": 5.0,
            "spacecraft_bus_current_a": 0.65,
            "battery_temperature_c": 28.0,
            "battery_state_of_charge_percent": 78.0,
            "obc_state": "NOMINAL",
        }

        # One-shot / persistent simulated faults
        self._force_crc_error_once = False
        self._force_parse_error_once = False
        self._drop_next_packet = False
        self._link_loss = False
        self._high_temperature = False
        self._low_voltage = False
        self._can_error = False
        self._can_bus_off = False
        self._weak_radio_link = False
        self._sdr_overrun = False

    @staticmethod
    def _drift(
        value: float,
        step: float,
        minimum: float,
        maximum: float,
    ) -> float:
        value += random.uniform(-step, step)
        return max(minimum, min(maximum, value))

    def _update_nominal_state(self) -> None:
        self.rpi_cpu_temperature_c = self._drift(
            self.rpi_cpu_temperature_c, 0.25, 40.0, 60.0
        )
        self.rpi_cpu_usage_percent = self._drift(
            self.rpi_cpu_usage_percent, 2.5, 4.0, 55.0
        )
        self.rpi_memory_usage_percent = self._drift(
            self.rpi_memory_usage_percent, 0.5, 25.0, 50.0
        )
        self.rpi_disk_usage_percent = self._drift(
            self.rpi_disk_usage_percent, 0.02, 20.0, 30.0
        )

        self.round_trip_latency_ms = self._drift(
            self.round_trip_latency_ms, 1.2, 2.0, 25.0
        )

        self.radio_rssi_dbm = self._drift(
            self.radio_rssi_dbm, 1.0, -85.0, -45.0
        )
        self.radio_snr_db = self._drift(
            self.radio_snr_db, 0.6, 4.0, 25.0
        )
        self.radio_pa_temperature_c = self._drift(
            self.radio_pa_temperature_c, 0.2, 35.0, 55.0
        )

        self.sdr_gain_db = self._drift(
            self.sdr_gain_db, 0.2, 15.0, 30.0
        )

        self.spacecraft_parameters["spacecraft_bus_voltage_v"] = self._drift(
            float(self.spacecraft_parameters["spacecraft_bus_voltage_v"]),
            0.02,
            4.8,
            5.2,
        )
        self.spacecraft_parameters["spacecraft_bus_current_a"] = self._drift(
            float(self.spacecraft_parameters["spacecraft_bus_current_a"]),
            0.03,
            0.3,
            1.0,
        )
        self.spacecraft_parameters["battery_temperature_c"] = self._drift(
            float(self.spacecraft_parameters["battery_temperature_c"]),
            0.15,
            22.0,
            36.0,
        )
        self.spacecraft_parameters["battery_state_of_charge_percent"] = self._drift(
            float(self.spacecraft_parameters["battery_state_of_charge_percent"]),
            0.08,
            65.0,
            90.0,
        )

    def _apply_persistent_faults(self) -> None:
        if self._high_temperature:
            self.rpi_cpu_temperature_c = self._drift(
                max(self.rpi_cpu_temperature_c, 82.0),
                0.3,
                80.0,
                92.0,
            )

        if self._low_voltage:
            self.spacecraft_parameters["spacecraft_bus_voltage_v"] = self._drift(
                min(
                    float(self.spacecraft_parameters["spacecraft_bus_voltage_v"]),
                    4.35,
                ),
                0.03,
                4.1,
                4.45,
            )

        if self._weak_radio_link:
            self.radio_rssi_dbm = self._drift(
                min(self.radio_rssi_dbm, -105.0),
                1.5,
                -118.0,
                -100.0,
            )
            self.radio_snr_db = self._drift(
                min(self.radio_snr_db, 1.5),
                0.4,
                -2.0,
                2.0,
            )

        if self._can_error:
            self.can_status = CANStatus.ERROR
            self.can_error_count += 1
            self.can_last_error_code = "SIM_CAN_ERROR"

        if self._can_bus_off:
            self.can_status = CANStatus.BUS_OFF
            self.can_bus_off_count += 1
            self.can_last_error_code = "SIM_BUS_OFF"

        if self._sdr_overrun:
            self.sdr_overrun_count += 1
            self.sdr_error_count += 1

        if self._link_loss:
            self.link_status = LinkStatus.DISCONNECTED
            self.heartbeat_ok = False
        elif self.link_status == LinkStatus.DISCONNECTED:
            self.link_status = LinkStatus.CONNECTED
            self.heartbeat_ok = True
            self.link_reconnect_count += 1

    def generate_frame(self) -> TelemetryFrame | None:
        """
        Generate one telemetry frame.

        Returns None when packet-drop injection is active.
        """

        self._update_nominal_state()
        self._apply_persistent_faults()

        if self._drop_next_packet:
            self._drop_next_packet = False
            self.packet_drop_count += 1
            self.radio_packet_loss_count += 1
            return None

        now = datetime.now(timezone.utc)
        uptime_s = time.monotonic() - self.start_monotonic

        self.sequence_number = (self.sequence_number + 1) & 0xFFFFFFFF
        self.packet_receive_count += 1

        if self.link_status == LinkStatus.CONNECTED:
            self.link_rx_message_count += 1
            self.last_rx_timestamp = now
            self.radio_rx_packet_count += 1
            self.radio_last_rx_timestamp = now
            self.sdr_rx_sample_count += int(
                self.sdr_sample_rate_sps * self.update_period_s
            )
            self.can_rx_frame_count += random.randint(0, 3)
            if self.can_rx_frame_count:
                self.can_last_rx_id = random.choice([0x100, 0x101, 0x200])
                self.can_last_rx_timestamp = now

        crc_status = CRCStatus.OK
        parse_status = ParseStatus.OK

        if self._force_crc_error_once:
            crc_status = CRCStatus.FAIL
            self._force_crc_error_once = False
            self.packet_crc_error_count += 1
            self.link_rx_error_count += 1

        if self._force_parse_error_once:
            parse_status = ParseStatus.INVALID_FIELD
            self._force_parse_error_once = False
            self.packet_parse_error_count += 1
            self.link_rx_error_count += 1

        meta = PacketMeta(
            protocol_version=1,
            message_type=MessageType.TELEMETRY,
            source_id=1,
            destination_id=100,
            packet_id=1,
            sequence_number=self.sequence_number,
            timestamp=now,
            payload_length=0,  # Final serialization is still TBD.
            crc_value=None,
            crc_status=crc_status,
            parse_status=parse_status,
        )

        raspberry = RaspberryTelemetry(
            uptime_s=uptime_s,
            cpu_temperature_c=self.rpi_cpu_temperature_c,
            cpu_usage_percent=self.rpi_cpu_usage_percent,
            memory_usage_percent=self.rpi_memory_usage_percent,
            memory_used_bytes=self.rpi_memory_used_bytes,
            disk_usage_percent=self.rpi_disk_usage_percent,
            network_status=self.link_status,
            network_rx_bytes=self.link_rx_message_count * 256,
            network_tx_bytes=self.link_tx_message_count * 128,
            process_status=(
                ProcessStatus.RUNNING
                if self.link_status == LinkStatus.CONNECTED
                else ProcessStatus.DEGRADED
            ),
            software_version="0.1.0-sim",
            restart_count=0,
            error_count=(
                self.packet_crc_error_count
                + self.packet_parse_error_count
                + self.link_rx_error_count
            ),
            last_error_code=(
                "SIM_LINK_LOSS"
                if self._link_loss
                else None
            ),
        )

        link = LinkTelemetry(
            status=self.link_status,
            last_rx_timestamp=self.last_rx_timestamp,
            last_tx_timestamp=self.last_tx_timestamp,
            rx_message_count=self.link_rx_message_count,
            tx_message_count=self.link_tx_message_count,
            rx_error_count=self.link_rx_error_count,
            tx_error_count=self.link_tx_error_count,
            reconnect_count=self.link_reconnect_count,
            round_trip_latency_ms=(
                None
                if self.link_status != LinkStatus.CONNECTED
                else self.round_trip_latency_ms
            ),
            heartbeat_ok=self.heartbeat_ok,
            heartbeat_age_ms=(
                None
                if self.link_status != LinkStatus.CONNECTED
                else int(self.update_period_s * 1000)
            ),
        )

        radio = RadioTelemetry(
            state=(
                RadioState.ERROR
                if self._weak_radio_link and self.radio_snr_db < 0
                else self.radio_state
            ),
            frequency_hz=self.radio_frequency_hz,
            rssi_dbm=self.radio_rssi_dbm,
            snr_db=self.radio_snr_db,
            tx_power_dbm=self.radio_tx_power_dbm,
            bitrate_bps=self.radio_bitrate_bps,
            channel_id=self.radio_channel_id,
            modulation=self.radio_modulation,
            rx_packet_count=self.radio_rx_packet_count,
            tx_packet_count=self.radio_tx_packet_count,
            rx_error_count=self.radio_rx_error_count,
            packet_loss_count=self.radio_packet_loss_count,
            pa_temperature_c=self.radio_pa_temperature_c,
            lock_status=self.radio_lock_status,
            last_rx_timestamp=self.radio_last_rx_timestamp,
        )

        sdr = SDRTelemetry(
            status=self.sdr_status,
            center_frequency_hz=self.sdr_center_frequency_hz,
            sample_rate_sps=self.sdr_sample_rate_sps,
            bandwidth_hz=self.sdr_bandwidth_hz,
            gain_db=self.sdr_gain_db,
            rx_sample_count=self.sdr_rx_sample_count,
            overrun_count=self.sdr_overrun_count,
            underrun_count=self.sdr_underrun_count,
            error_count=self.sdr_error_count,
        )

        can = CANTelemetry(
            status=self.can_status,
            bitrate_bps=self.can_bitrate_bps,
            rx_frame_count=self.can_rx_frame_count,
            tx_frame_count=self.can_tx_frame_count,
            error_count=self.can_error_count,
            bus_off_count=self.can_bus_off_count,
            last_rx_id=self.can_last_rx_id,
            last_tx_id=self.can_last_tx_id,
            last_rx_timestamp=self.can_last_rx_timestamp,
            last_error_code=self.can_last_error_code,
        )

        spacecraft = SpacecraftTelemetry(
            parameters=dict(self.spacecraft_parameters)
        )

        return TelemetryFrame(
            meta=meta,
            raspberry=raspberry,
            link=link,
            radio=radio,
            sdr=sdr,
            can=can,
            spacecraft=spacecraft,
            raw_packet=b"",
        )

    # ------------------------------------------------------------------
    # Fault injection API
    # ------------------------------------------------------------------

    def inject_crc_error(self) -> None:
        self._force_crc_error_once = True

    def inject_parse_error(self) -> None:
        self._force_parse_error_once = True

    def inject_packet_drop(self) -> None:
        self._drop_next_packet = True

    def set_link_loss(self, enabled: bool = True) -> None:
        self._link_loss = enabled

    def set_high_temperature(self, enabled: bool = True) -> None:
        self._high_temperature = enabled

    def set_low_voltage(self, enabled: bool = True) -> None:
        self._low_voltage = enabled

    def set_can_error(self, enabled: bool = True) -> None:
        self._can_error = enabled
        if not enabled and not self._can_bus_off:
            self.can_status = CANStatus.UP
            self.can_last_error_code = None

    def set_can_bus_off(self, enabled: bool = True) -> None:
        self._can_bus_off = enabled
        if not enabled and not self._can_error:
            self.can_status = CANStatus.UP
            self.can_last_error_code = None

    def set_weak_radio_link(self, enabled: bool = True) -> None:
        self._weak_radio_link = enabled

    def set_sdr_overrun(self, enabled: bool = True) -> None:
        self._sdr_overrun = enabled

    def clear_faults(self) -> None:
        self._force_crc_error_once = False
        self._force_parse_error_once = False
        self._drop_next_packet = False
        self._link_loss = False
        self._high_temperature = False
        self._low_voltage = False
        self._can_error = False
        self._can_bus_off = False
        self._weak_radio_link = False
        self._sdr_overrun = False

        self.link_status = LinkStatus.CONNECTED
        self.heartbeat_ok = True
        self.can_status = CANStatus.UP
        self.can_last_error_code = None
        self.sdr_status = SDRStatus.RECEIVING

    # ------------------------------------------------------------------
    # Command simulation helpers
    # ------------------------------------------------------------------

    def simulate_command_sent(self) -> None:
        self.link_tx_message_count += 1
        self.last_tx_timestamp = datetime.now(timezone.utc)

    def simulate_can_transmit(self, can_id: int) -> None:
        self.can_tx_frame_count += 1
        self.can_last_tx_id = can_id

    def simulate_radio_transmit(self) -> None:
        self.radio_tx_packet_count += 1
