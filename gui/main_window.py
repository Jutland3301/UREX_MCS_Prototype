from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from common.enums import CANStatus, CRCStatus, LinkStatus, RadioState, SDRStatus
from common.telemetry import TelemetryFrame
from simulator.telemetry_simulator import TelemetrySimulator


class MainWindow(QMainWindow):
    """
    Prototype MCS GUI.

    The GUI consumes TelemetryFrame objects only. It does not know whether
    those frames originated from a simulator, ZeroMQ, MQTT, or real hardware.
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("UREX Mission Control System")
        self.resize(1180, 820)

        self.simulator = TelemetrySimulator(update_period_s=1.0)

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_simulator)
        self.timer.start(1000)

        self._append_log("INFO", "MCS", "Application started")
        self._append_log("INFO", "SIM", "Telemetry simulator connected")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)

        top = QHBoxLayout()
        top.addWidget(self._build_system_status_group(), 1)
        top.addWidget(self._build_telemetry_group(), 2)
        root.addLayout(top)

        root.addWidget(self._build_packet_monitor_group(), 2)
        root.addWidget(self._build_command_group())
        root.addWidget(self._build_event_log_group(), 1)

    def _status_label(self, initial: str = "-") -> QLabel:
        label = QLabel(initial)
        label.setMinimumWidth(120)
        return label

    def _build_system_status_group(self) -> QGroupBox:
        group = QGroupBox("Connection / System Status")
        layout = QFormLayout(group)

        self.transport_label = self._status_label("SIMULATOR")
        self.link_status_label = self._status_label()
        self.heartbeat_label = self._status_label()
        self.rpi_status_label = self._status_label()
        self.radio_status_label = self._status_label()
        self.sdr_status_label = self._status_label()
        self.can_status_label = self._status_label()
        self.last_packet_label = self._status_label()
        self.error_count_label = self._status_label("0")

        layout.addRow("Transport:", self.transport_label)
        layout.addRow("MCS Link:", self.link_status_label)
        layout.addRow("Heartbeat:", self.heartbeat_label)
        layout.addRow("Raspberry Pi:", self.rpi_status_label)
        layout.addRow("Radio:", self.radio_status_label)
        layout.addRow("SDR:", self.sdr_status_label)
        layout.addRow("CAN:", self.can_status_label)
        layout.addRow("Last Packet:", self.last_packet_label)
        layout.addRow("Errors:", self.error_count_label)

        return group

    def _build_telemetry_group(self) -> QGroupBox:
        group = QGroupBox("Telemetry")
        layout = QHBoxLayout(group)

        rpi_group = QGroupBox("Raspberry Pi")
        rpi_form = QFormLayout(rpi_group)

        self.rpi_cpu_temp_label = self._status_label()
        self.rpi_cpu_usage_label = self._status_label()
        self.rpi_memory_label = self._status_label()
        self.rpi_disk_label = self._status_label()
        self.rpi_uptime_label = self._status_label()

        rpi_form.addRow("CPU Temp:", self.rpi_cpu_temp_label)
        rpi_form.addRow("CPU Usage:", self.rpi_cpu_usage_label)
        rpi_form.addRow("Memory:", self.rpi_memory_label)
        rpi_form.addRow("Disk:", self.rpi_disk_label)
        rpi_form.addRow("Uptime:", self.rpi_uptime_label)

        radio_group = QGroupBox("Radio / RF")
        radio_form = QFormLayout(radio_group)

        self.frequency_label = self._status_label()
        self.rssi_label = self._status_label()
        self.snr_label = self._status_label()
        self.tx_power_label = self._status_label()
        self.radio_pa_temp_label = self._status_label()

        radio_form.addRow("Frequency:", self.frequency_label)
        radio_form.addRow("RSSI:", self.rssi_label)
        radio_form.addRow("SNR:", self.snr_label)
        radio_form.addRow("TX Power:", self.tx_power_label)
        radio_form.addRow("PA Temp:", self.radio_pa_temp_label)

        spacecraft_group = QGroupBox("Spacecraft (Placeholder)")
        spacecraft_form = QFormLayout(spacecraft_group)

        self.bus_voltage_label = self._status_label()
        self.bus_current_label = self._status_label()
        self.battery_temp_label = self._status_label()
        self.battery_soc_label = self._status_label()
        self.obc_state_label = self._status_label()

        spacecraft_form.addRow("Bus Voltage:", self.bus_voltage_label)
        spacecraft_form.addRow("Bus Current:", self.bus_current_label)
        spacecraft_form.addRow("Battery Temp:", self.battery_temp_label)
        spacecraft_form.addRow("Battery SOC:", self.battery_soc_label)
        spacecraft_form.addRow("OBC State:", self.obc_state_label)

        layout.addWidget(rpi_group)
        layout.addWidget(radio_group)
        layout.addWidget(spacecraft_group)

        return group

    def _build_packet_monitor_group(self) -> QGroupBox:
        group = QGroupBox("Packet Monitor")
        layout = QVBoxLayout(group)

        self.packet_table = QTableWidget(0, 8)
        self.packet_table.setHorizontalHeaderLabels(
            [
                "Time",
                "Seq",
                "Source",
                "Type",
                "Packet ID",
                "Length",
                "CRC",
                "Parse",
            ]
        )
        self.packet_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.packet_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.packet_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )

        layout.addWidget(self.packet_table)
        return group

    def _build_command_group(self) -> QGroupBox:
        group = QGroupBox("Command Panel")
        layout = QHBoxLayout(group)

        self.command_combo = QComboBox()
        self.command_combo.addItems(
            [
                "PING",
                "REQUEST_STATUS",
                "SET_MODE",
                "RADIO_ENABLE",
                "RADIO_DISABLE",
                "RADIO_SET_FREQUENCY",
                "SDR_START_RX",
                "SDR_STOP_RX",
                "CAN_SEND_FRAME",
                "SIM_INJECT_CRC_ERROR",
                "SIM_INJECT_PACKET_DROP",
                "SIM_INJECT_LINK_LOSS",
                "SIM_INJECT_HIGH_TEMPERATURE",
                "SIM_INJECT_LOW_VOLTAGE",
                "SIM_INJECT_CAN_ERROR",
                "SIM_INJECT_CAN_BUS_OFF",
                "SIM_INJECT_WEAK_RADIO",
                "SIM_INJECT_SDR_OVERRUN",
                "SIM_RESET_FAULTS",
            ]
        )

        self.command_parameter = QLineEdit()
        self.command_parameter.setPlaceholderText("Optional parameter")

        send_button = QPushButton("Send")
        send_button.clicked.connect(self._send_command)

        layout.addWidget(QLabel("Command:"))
        layout.addWidget(self.command_combo, 2)
        layout.addWidget(QLabel("Parameter:"))
        layout.addWidget(self.command_parameter, 2)
        layout.addWidget(send_button)

        return group

    def _build_event_log_group(self) -> QGroupBox:
        group = QGroupBox("Event / Error Log")
        layout = QVBoxLayout(group)

        self.event_log = QTextEdit()
        self.event_log.setReadOnly(True)

        layout.addWidget(self.event_log)
        return group

    # ------------------------------------------------------------------
    # Telemetry update
    # ------------------------------------------------------------------

    def _poll_simulator(self) -> None:
        frame = self.simulator.generate_frame()

        if frame is None:
            self._append_log("WARNING", "SIM", "Simulated packet drop")
            return

        self.update_telemetry(frame)

    def update_telemetry(self, frame: TelemetryFrame) -> None:
        """
        Public GUI update entry point.

        Future QThread/Signal-Slot receivers should emit TelemetryFrame objects
        and connect them to this method.
        """

        self._update_status_panel(frame)
        self._update_telemetry_panel(frame)
        self._append_packet_row(frame)

        if frame.meta.crc_status == CRCStatus.FAIL:
            self._append_log(
                "ERROR",
                "PACKET",
                f"CRC validation failed for sequence {frame.meta.sequence_number}",
            )

        if frame.meta.parse_status.value != "OK":
            self._append_log(
                "ERROR",
                "PACKET",
                f"Parse failure for sequence {frame.meta.sequence_number}: "
                f"{frame.meta.parse_status.value}",
            )

        if frame.link.status != LinkStatus.CONNECTED:
            self._append_log(
                "WARNING",
                "LINK",
                f"MCS link status: {frame.link.status.value}",
            )

        if frame.can.status in {CANStatus.ERROR, CANStatus.BUS_OFF}:
            self._append_log(
                "ERROR",
                "CAN",
                f"CAN status: {frame.can.status.value}",
            )

    def _update_status_panel(self, frame: TelemetryFrame) -> None:
        self.link_status_label.setText(frame.link.status.value)
        self.heartbeat_label.setText(
            "OK" if frame.link.heartbeat_ok else "LOST"
        )
        self.rpi_status_label.setText(frame.raspberry.process_status.value)
        self.radio_status_label.setText(frame.radio.state.value)
        self.sdr_status_label.setText(frame.sdr.status.value)
        self.can_status_label.setText(frame.can.status.value)

        self.last_packet_label.setText(
            frame.meta.timestamp.astimezone().strftime("%H:%M:%S")
        )

        total_errors = (
            frame.raspberry.error_count
            + frame.radio.rx_error_count
            + frame.sdr.error_count
            + frame.can.error_count
        )
        self.error_count_label.setText(str(total_errors))

    def _update_telemetry_panel(self, frame: TelemetryFrame) -> None:
        self.rpi_cpu_temp_label.setText(
            self._fmt(frame.raspberry.cpu_temperature_c, "°C")
        )
        self.rpi_cpu_usage_label.setText(
            self._fmt(frame.raspberry.cpu_usage_percent, "%")
        )
        self.rpi_memory_label.setText(
            self._fmt(frame.raspberry.memory_usage_percent, "%")
        )
        self.rpi_disk_label.setText(
            self._fmt(frame.raspberry.disk_usage_percent, "%")
        )
        self.rpi_uptime_label.setText(
            self._fmt(frame.raspberry.uptime_s, "s", decimals=0)
        )

        if frame.radio.frequency_hz is not None:
            self.frequency_label.setText(
                f"{frame.radio.frequency_hz / 1_000_000:.3f} MHz"
            )
        else:
            self.frequency_label.setText("-")

        self.rssi_label.setText(
            self._fmt(frame.radio.rssi_dbm, "dBm")
        )
        self.snr_label.setText(
            self._fmt(frame.radio.snr_db, "dB")
        )
        self.tx_power_label.setText(
            self._fmt(frame.radio.tx_power_dbm, "dBm")
        )
        self.radio_pa_temp_label.setText(
            self._fmt(frame.radio.pa_temperature_c, "°C")
        )

        sc = frame.spacecraft.parameters
        self.bus_voltage_label.setText(
            self._fmt(sc.get("spacecraft_bus_voltage_v"), "V", decimals=3)
        )
        self.bus_current_label.setText(
            self._fmt(sc.get("spacecraft_bus_current_a"), "A", decimals=3)
        )
        self.battery_temp_label.setText(
            self._fmt(sc.get("battery_temperature_c"), "°C")
        )
        self.battery_soc_label.setText(
            self._fmt(
                sc.get("battery_state_of_charge_percent"),
                "%",
            )
        )
        self.obc_state_label.setText(str(sc.get("obc_state", "-")))

    def _append_packet_row(self, frame: TelemetryFrame) -> None:
        row = self.packet_table.rowCount()
        self.packet_table.insertRow(row)

        values = [
            frame.meta.timestamp.astimezone().strftime("%H:%M:%S"),
            str(frame.meta.sequence_number),
            str(frame.meta.source_id),
            frame.meta.message_type.value,
            f"0x{frame.meta.packet_id:04X}",
            str(frame.meta.payload_length),
            frame.meta.crc_status.value,
            frame.meta.parse_status.value,
        ]

        for column, value in enumerate(values):
            self.packet_table.setItem(
                row,
                column,
                QTableWidgetItem(value),
            )

        # Keep recent history only.
        while self.packet_table.rowCount() > 200:
            self.packet_table.removeRow(0)

        self.packet_table.scrollToBottom()

    # ------------------------------------------------------------------
    # Command panel
    # ------------------------------------------------------------------

    def _send_command(self) -> None:
        command = self.command_combo.currentText()
        parameter = self.command_parameter.text().strip()

        self.simulator.simulate_command_sent()

        if command == "SIM_INJECT_CRC_ERROR":
            self.simulator.inject_crc_error()

        elif command == "SIM_INJECT_PACKET_DROP":
            self.simulator.inject_packet_drop()

        elif command == "SIM_INJECT_LINK_LOSS":
            self.simulator.set_link_loss(True)

        elif command == "SIM_INJECT_HIGH_TEMPERATURE":
            self.simulator.set_high_temperature(True)

        elif command == "SIM_INJECT_LOW_VOLTAGE":
            self.simulator.set_low_voltage(True)

        elif command == "SIM_INJECT_CAN_ERROR":
            self.simulator.set_can_error(True)

        elif command == "SIM_INJECT_CAN_BUS_OFF":
            self.simulator.set_can_bus_off(True)

        elif command == "SIM_INJECT_WEAK_RADIO":
            self.simulator.set_weak_radio_link(True)

        elif command == "SIM_INJECT_SDR_OVERRUN":
            self.simulator.set_sdr_overrun(True)

        elif command == "SIM_RESET_FAULTS":
            self.simulator.clear_faults()

        elif command == "CAN_SEND_FRAME":
            try:
                can_id = int(parameter, 0) if parameter else 0x100
            except ValueError:
                self._append_log(
                    "ERROR",
                    "COMMAND",
                    f"Invalid CAN ID: {parameter}",
                )
                return

            self.simulator.simulate_can_transmit(can_id)

        elif command == "RADIO_SET_FREQUENCY":
            if not parameter:
                self._append_log(
                    "ERROR",
                    "COMMAND",
                    "RADIO_SET_FREQUENCY requires a frequency in Hz",
                )
                return

            try:
                self.simulator.radio_frequency_hz = int(parameter)
            except ValueError:
                self._append_log(
                    "ERROR",
                    "COMMAND",
                    f"Invalid frequency: {parameter}",
                )
                return

        elif command == "RADIO_ENABLE":
            self.simulator.radio_state = RadioState.RX

        elif command == "RADIO_DISABLE":
            self.simulator.radio_state = RadioState.OFF

        elif command == "SDR_START_RX":
            self.simulator.sdr_status = SDRStatus.RECEIVING

        elif command == "SDR_STOP_RX":
            self.simulator.sdr_status = SDRStatus.IDLE

        elif command == "PING":
            pass

        elif command == "REQUEST_STATUS":
            pass

        elif command == "SET_MODE":
            self.simulator.spacecraft_parameters["obc_state"] = (
                parameter.upper() if parameter else "NOMINAL"
            )

        suffix = f" parameter={parameter}" if parameter else ""
        self._append_log(
            "INFO",
            "COMMAND",
            f"Sent {command}{suffix}",
        )

    # ------------------------------------------------------------------
    # Logging/helpers
    # ------------------------------------------------------------------

    def _append_log(
        self,
        severity: str,
        source: str,
        message: str,
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.event_log.append(
            f"[{timestamp}] [{severity}] [{source}] {message}"
        )

    @staticmethod
    def _fmt(
        value: object,
        unit: str,
        decimals: int = 1,
    ) -> str:
        if value is None:
            return "-"

        if isinstance(value, (int, float)):
            return f"{value:.{decimals}f} {unit}"

        return f"{value} {unit}"
