from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from common.enums import CANStatus, LinkStatus, RadioState, SDRStatus
from common.telemetry import TelemetryFrame
from common.telemetry_state import TelemetryState
from communication.base_transport import TransportStatus
from communication.simulated_transport import SimulatedTransport
from gui.experiment_panel import ExperimentPanel
from gui.simulator_control_panel import SimulatorControlPanel
from measurement.metrics_collector import MetricsCollector
from packet.encoder import PacketEncoder
from packet.parser import PacketParser, ParseResult
from packet.profiles import PROVISIONAL_PROFILE
from simulator.manual_packet_source import ManualPacketSource
from simulator.scenario_config import NetworkConditions, ScenarioConfig
from simulator.scenario_controller import ExperimentState, ScenarioController
from simulator.telemetry_simulator import TelemetrySimulator

class MainWindow(QMainWindow):
    """
    Prototype MCS GUI.

    The GUI consumes TelemetryFrame objects only. It does not know whether
    those frames originated from a simulator, ZeroMQ, MQTT, or real hardware.
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("UREX MCS Simulator v0.3.b")
        self.resize(1180, 820)

        self.profile = PROVISIONAL_PROFILE
        self.encoder = PacketEncoder(self.profile)
        self.parser = PacketParser(self.profile)
        self.telemetry_state = TelemetryState(self.profile)
        self.scenario_path = (
            Path(__file__).resolve().parents[1] / "scenarios" / "default.json"
        )
        self.scenario = ScenarioConfig.load(self.scenario_path)
        self.source = ManualPacketSource(self.profile, self.scenario)
        self.telemetry_simulator = TelemetrySimulator()
        self._active_fault_packets: set[str] = set()
        self._active_fault_commands: dict[str, set[str]] = {}
        self._fault_original_values: dict[tuple[str, str], object] = {}
        self.metrics = MetricsCollector()
        self.transport = SimulatedTransport(
            self.scenario.network,
            random_seed=self.scenario.random_seed,
        )
        self.controller = ScenarioController(
            self.source,
            self.encoder,
            self.transport,
            self.metrics,
            before_encode=self._sync_simulated_faults,
        )
        self._last_alert_link_status: LinkStatus | None = None
        self._last_alert_can_status: CANStatus | None = None

        self._build_ui()

        self.transport.set_message_handler(self._handle_raw_message)
        self.transport.set_status_handler(self._handle_transport_status)
        self.transport.set_event_handler(self.metrics.record_transport_event)
        self.transport.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._experiment_tick)
        self.timer.start(self.scenario.experiment.scheduler_interval_ms)

        self._append_log("INFO", "MCS", "Application started")
        self._append_log(
            "INFO",
            "SIM",
            f"Manual experiment simulator ready using {self.profile.name}",
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        tabs = QTabWidget()
        root.addWidget(tabs)

        monitor_page = QWidget()
        monitor = QVBoxLayout(monitor_page)
        top = QHBoxLayout()
        top.addWidget(self._build_system_status_group(), 1)
        top.addWidget(self._build_telemetry_group(), 2)
        monitor.addLayout(top)

        monitor.addWidget(self._build_packet_monitor_group(), 2)
        monitor.addWidget(self._build_command_group())
        monitor.addWidget(self._build_event_log_group(), 1)
        tabs.addTab(monitor_page, "MCS Monitor")

        experiment_page = QWidget()
        experiment_layout = QHBoxLayout(experiment_page)
        self.simulator_control_panel = SimulatorControlPanel(self.source)
        self.simulator_control_panel.set_network_conditions(self.scenario.network)
        self.experiment_panel = ExperimentPanel(
            self.scenario.experiment.duration_s,
            self.scenario.experiment.burst_size,
        )
        experiment_layout.addWidget(self.simulator_control_panel, 3)
        experiment_layout.addWidget(self.experiment_panel, 2)
        tabs.addTab(experiment_page, "Simulator Experiment")

        self._connect_experiment_controls()

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

        self.packet_table = QTableWidget(0, 9)
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
                "Raw Hex",
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
    def _activate_equipment_fault(self, command: str, packet_name: str) -> None:
        affected_fields = {
            "RPI_STATUS": ("cpu_temperature_c",),
            "SPACECRAFT_POWER": ("spacecraft_bus_voltage_v",),
            "CAN_STATUS": ("status", "error_count", "bus_off_count"),
            "RADIO_STATUS": ("state", "rssi_dbm", "snr_db"),
            "SDR_STATUS": ("overrun_count", "error_count"),
        }
        for field_name in affected_fields[packet_name]:
            key = (packet_name, field_name)
            if key not in self._fault_original_values:
                self._fault_original_values[key] = self.source.get_value(*key)
        self._active_fault_packets.add(packet_name)
        self._active_fault_commands.setdefault(packet_name, set()).add(command)

    def _sync_simulated_faults(self, packet_name: str) -> None:
        """Apply only active equipment faults before encoding a packet."""
        if packet_name not in self._active_fault_packets:
            return

        frame = self.telemetry_simulator.generate_frame()
        if frame is None:
            raise RuntimeError("telemetry simulator did not produce a frame")

        if packet_name == "RPI_STATUS":
            values = {"cpu_temperature_c": frame.raspberry.cpu_temperature_c}
        elif packet_name == "SPACECRAFT_POWER":
            values = {
                "spacecraft_bus_voltage_v": frame.spacecraft.parameters[
                    "spacecraft_bus_voltage_v"
                ]
            }
        elif packet_name == "CAN_STATUS":
            values = {
                "status": frame.can.status,
                "error_count": frame.can.error_count,
                "bus_off_count": frame.can.bus_off_count,
            }
        elif packet_name == "RADIO_STATUS":
            values = {
                "state": frame.radio.state,
                "rssi_dbm": frame.radio.rssi_dbm,
                "snr_db": frame.radio.snr_db,
            }
        elif packet_name == "SDR_STATUS":
            values = {
                "overrun_count": frame.sdr.overrun_count,
                "error_count": frame.sdr.error_count,
            }
        else:
            return

        for field_name, value in values.items():
            self.source.set_value(packet_name, field_name, value)
        self.metrics.record_equipment_fault_packet(
            self._active_fault_commands.get(packet_name, ())
        )

    def _experiment_tick(self) -> None:
        previous_state = self.controller.state
        self.controller.tick()
        self.experiment_panel.update_state(self.controller.state)
        self.experiment_panel.update_metrics(
            self.metrics.snapshot(self.transport.queue_depth)
        )

        if previous_state != self.controller.state:
            self._append_log(
                "INFO",
                "EXPERIMENT",
                f"State changed to {self.controller.state.value}",
            )

        if self.controller.state in {
            ExperimentState.RUNNING,
            ExperimentState.PAUSED,
        }:
            self.update_telemetry(self.telemetry_state.refresh_staleness())

    def _handle_raw_message(self, raw_packet: bytes) -> None:
        result = self.parser.parse(raw_packet)
        self.metrics.record_parse_result(result)
        self._append_packet_result(result)

        if not result.ok:
            frame = self.telemetry_state.record_parse_failure()
            self._update_status_panel(frame)
            details = "; ".join(result.errors) or "unknown parser error"
            self._append_log(
                "ERROR",
                "PACKET",
                f"{result.status.value}: {details}",
            )
            return

        frame = self.telemetry_state.apply(result)
        self.update_telemetry(frame)

    def _handle_transport_status(self, status: TransportStatus) -> None:
        self.transport_label.setText(f"{self.transport.name} / {status.value}")
        if status in {
            TransportStatus.STOPPED,
            TransportStatus.DISCONNECTED,
            TransportStatus.ERROR,
        }:
            self.update_telemetry(
                self.telemetry_state.set_transport_connected(False)
            )

    def update_telemetry(self, frame: TelemetryFrame) -> None:
        """
        Public GUI update entry point.

        Future QThread/Signal-Slot receivers should emit TelemetryFrame objects
        and connect them to this method.
        """

        self._update_status_panel(frame)
        self._update_telemetry_panel(frame)

        if (
            frame.link.status != LinkStatus.CONNECTED
            and frame.link.status != self._last_alert_link_status
        ):
            self._append_log(
                "WARNING",
                "LINK",
                f"MCS link status: {frame.link.status.value}",
            )
        self._last_alert_link_status = frame.link.status

        if (
            frame.can.status in {CANStatus.ERROR, CANStatus.BUS_OFF}
            and frame.can.status != self._last_alert_can_status
        ):
            self._append_log(
                "ERROR",
                "CAN",
                f"CAN status: {frame.can.status.value}",
            )
        self._last_alert_can_status = frame.can.status

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
            + frame.link.rx_error_count
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

    def _append_packet_result(self, result: ParseResult) -> None:
        row = self.packet_table.rowCount()
        self.packet_table.insertRow(row)

        meta = result.packet.meta if result.packet is not None else None
        # The framing header contains only magic, version and payload length.
        # Sequence/source/type/packet ID exist only in decoded Protobuf metadata.
        values = [
            datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"),
            str(meta.sequence_number) if meta is not None else "-",
            str(meta.source_id) if meta is not None else "-",
            meta.message_type.value if meta is not None else "-",
            f"0x{meta.packet_id:04X}" if meta is not None else "-",
            str(len(result.raw_packet)),
            result.application_crc_status.value,
            result.status.value,
            result.raw_packet.hex(" ").upper(),
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

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.controller.stop()
        self.transport.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Simulator experiment controls
    # ------------------------------------------------------------------

    def _connect_experiment_controls(self) -> None:
        controls = self.simulator_control_panel
        controls.field_update_requested.connect(self._set_manual_field)
        controls.period_update_requested.connect(self._set_packet_period)
        controls.send_once_requested.connect(self._send_manual_packet)
        controls.raw_packet_requested.connect(self._send_raw_packet)
        controls.network_update_requested.connect(self._set_network_conditions)
        controls.save_scenario_requested.connect(self._save_scenario)

        experiment = self.experiment_panel
        experiment.start_requested.connect(self._start_experiment)
        experiment.pause_resume_requested.connect(self._pause_resume_experiment)
        experiment.stop_requested.connect(self._stop_experiment)
        experiment.export_requested.connect(self._export_results)

    def _set_manual_field(
        self,
        packet_name: str,
        field_name: str,
        value: str,
    ) -> None:
        try:
            converted = self.source.set_value(packet_name, field_name, value)
        except (RuntimeError, ValueError) as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)
            return
        key = (packet_name, field_name)
        if key in self._fault_original_values:
            self._fault_original_values[key] = converted
        self.simulator_control_panel.refresh_current_value()
        self.simulator_control_panel.set_message(
            f"Applied {packet_name}.{field_name}={converted}"
        )

    def _set_packet_period(self, packet_name: str, period_s: float) -> None:
        try:
            self.source.set_period_s(packet_name, period_s)
        except (RuntimeError, ValueError) as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)

    def _send_manual_packet(
        self,
        packet_name: str,
        force_drop: bool,
        force_corrupt: bool,
    ) -> None:
        try:
            result = self.controller.send_once(
                packet_name,
                force_drop=force_drop,
                force_corrupt=force_corrupt,
            )
        except (RuntimeError, ValueError) as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)
            return
        self.simulator_control_panel.set_message(
            f"{packet_name}: {result}"
        )

    def _send_raw_packet(self, raw_hex: str) -> None:
        try:
            result = self.controller.send_raw_hex(raw_hex)
        except (RuntimeError, ValueError) as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)
            return
        self.simulator_control_panel.set_message(f"Raw packet: {result}")

    def _set_network_conditions(
        self,
        drop_percent: float,
        corruption_percent: float,
        delay_ms: float,
        jitter_ms: float,
    ) -> None:
        conditions = NetworkConditions(
            drop_rate_percent=drop_percent,
            corruption_rate_percent=corruption_percent,
            delay_ms=delay_ms,
            jitter_ms=jitter_ms,
        )
        try:
            self.transport.configure(conditions)
        except ValueError as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)
            return
        self.scenario.network = conditions
        self.simulator_control_panel.set_network_conditions(conditions)
        self.simulator_control_panel.set_message("Network conditions applied")

    def _start_experiment(self, duration_s: float, burst_size: int) -> None:
        self.packet_table.setRowCount(0)
        self.controller.start(duration_s, burst_size)
        for commands in self._active_fault_commands.values():
            for command in commands:
                self.metrics.record_fault_injection(command)
        self.experiment_panel.update_state(self.controller.state)
        self._append_log(
            "INFO",
            "EXPERIMENT",
            f"Started duration={duration_s:.1f}s burst={burst_size}",
        )

    def _pause_resume_experiment(self) -> None:
        if self.controller.state == ExperimentState.RUNNING:
            self.controller.pause()
        elif self.controller.state == ExperimentState.PAUSED:
            self.controller.resume()
        self.experiment_panel.update_state(self.controller.state)

    def _stop_experiment(self) -> None:
        self.controller.stop()
        self.experiment_panel.update_state(self.controller.state)
        self._append_log("INFO", "EXPERIMENT", "Stopped by operator")

    def _save_scenario(self) -> None:
        self.scenario.experiment.duration_s = (
            self.experiment_panel.duration_spin.value()
        )
        self.scenario.experiment.burst_size = (
            self.experiment_panel.burst_spin.value()
        )
        try:
            self.scenario.save(self.scenario_path)
        except (OSError, ValueError) as exc:
            self.simulator_control_panel.set_message(str(exc), error=True)
            return
        self.simulator_control_panel.set_message(
            f"Saved {self.scenario_path.name}"
        )

    def _export_results(self, file_format: str) -> None:
        output_directory = Path(__file__).resolve().parents[1] / "results"
        output_directory.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).astimezone().strftime(
            "%Y%m%d_%H%M%S"
        )
        output = output_directory / f"experiment_{timestamp}.{file_format}"
        if file_format == "csv":
            self.metrics.export_csv(output, self.transport.queue_depth)
        else:
            self.metrics.export_json(output, self.transport.queue_depth)
        self._append_log("INFO", "EXPERIMENT", f"Exported {output}")

    # ------------------------------------------------------------------
    # Command panel
    # ------------------------------------------------------------------

    def _send_command(self) -> None:
        command = self.command_combo.currentText()
        parameter = self.command_parameter.text().strip()
        selected_packet = self.simulator_control_panel.selected_packet_name

        try:
            if command == "SIM_INJECT_CRC_ERROR":
                self.controller.send_once(selected_packet, force_corrupt=True)

            elif command == "SIM_INJECT_PACKET_DROP":
                self.controller.send_once(selected_packet, force_drop=True)

            elif command == "SIM_INJECT_LINK_LOSS":
                self.telemetry_simulator.set_link_loss(True)
                # Stop the timed sender before stopping its transport; otherwise
                # the next scheduler tick attempts to submit to a stopped link.
                self.controller.stop()
                self.experiment_panel.update_state(self.controller.state)
                self.transport.stop()

            elif command == "SIM_INJECT_HIGH_TEMPERATURE":
                self.telemetry_simulator.set_high_temperature(True)
                self._activate_equipment_fault(command, "RPI_STATUS")

            elif command == "SIM_INJECT_LOW_VOLTAGE":
                self.telemetry_simulator.set_low_voltage(True)
                self._activate_equipment_fault(command, "SPACECRAFT_POWER")

            elif command == "SIM_INJECT_CAN_ERROR":
                self.telemetry_simulator.set_can_error(True)
                self._activate_equipment_fault(command, "CAN_STATUS")

            elif command == "SIM_INJECT_CAN_BUS_OFF":
                self.telemetry_simulator.set_can_bus_off(True)
                self._activate_equipment_fault(command, "CAN_STATUS")

            elif command == "SIM_INJECT_WEAK_RADIO":
                self.telemetry_simulator.set_weak_radio_link(True)
                self._activate_equipment_fault(command, "RADIO_STATUS")

            elif command == "SIM_INJECT_SDR_OVERRUN":
                self.telemetry_simulator.set_sdr_overrun(True)
                self._activate_equipment_fault(command, "SDR_STATUS")

            elif command == "SIM_RESET_FAULTS":
                self.telemetry_simulator.clear_faults()
                for (packet_name, field_name), value in self._fault_original_values.items():
                    self.source.set_value(packet_name, field_name, value)
                self._fault_original_values.clear()
                self._active_fault_packets.clear()
                self._active_fault_commands.clear()
                self.transport.start()
                self._set_network_conditions(0.0, 0.0, 0.0, 0.0)
                self.telemetry_simulator.rpi_cpu_temperature_c = self.source.get_value(
                    "RPI_STATUS", "cpu_temperature_c"
                )
                self.telemetry_simulator.spacecraft_parameters[
                    "spacecraft_bus_voltage_v"
                ] = self.source.get_value(
                    "SPACECRAFT_POWER", "spacecraft_bus_voltage_v"
                )
                self.telemetry_simulator.can_status = self.source.get_value(
                    "CAN_STATUS", "status"
                )
                self.telemetry_simulator.can_error_count = self.source.get_value(
                    "CAN_STATUS", "error_count"
                )
                self.telemetry_simulator.can_bus_off_count = self.source.get_value(
                    "CAN_STATUS", "bus_off_count"
                )
                self.telemetry_simulator.radio_rssi_dbm = self.source.get_value(
                    "RADIO_STATUS", "rssi_dbm"
                )
                self.telemetry_simulator.radio_snr_db = self.source.get_value(
                    "RADIO_STATUS", "snr_db"
                )
                self.telemetry_simulator.radio_state = self.source.get_value(
                    "RADIO_STATUS", "state"
                )
                self.telemetry_simulator.sdr_overrun_count = self.source.get_value(
                    "SDR_STATUS", "overrun_count"
                )
                self.telemetry_simulator.sdr_error_count = self.source.get_value(
                    "SDR_STATUS", "error_count"
                )
                self.telemetry_simulator.sdr_status = self.source.get_value(
                    "SDR_STATUS", "status"
                )
                self.simulator_control_panel.refresh_current_value()

            elif command == "CAN_SEND_FRAME":
                can_id = int(parameter, 0) if parameter else 0x100
                self.source.set_value("CAN_STATUS", "last_tx_id", can_id)
                self.telemetry_simulator.can_tx_frame_count = int(
                    self.source.get_value("CAN_STATUS", "tx_frame_count")
                )
                self.telemetry_simulator.simulate_can_transmit(can_id)
                self.source.set_value(
                    "CAN_STATUS", "tx_frame_count",
                    self.telemetry_simulator.can_tx_frame_count,
                )

            elif command == "RADIO_SET_FREQUENCY":
                if not parameter:
                    raise ValueError(
                        "RADIO_SET_FREQUENCY requires a frequency in Hz"
                    )
                frequency_hz = int(parameter)
                self.source.set_value(
                    "RADIO_STATUS", "frequency_hz", frequency_hz
                )
                self.telemetry_simulator.radio_frequency_hz = frequency_hz

            elif command == "RADIO_ENABLE":
                self.source.set_value("RADIO_STATUS", "state", RadioState.RX)
                self.telemetry_simulator.radio_state = RadioState.RX
                if ("RADIO_STATUS", "state") in self._fault_original_values:
                    self._fault_original_values[("RADIO_STATUS", "state")] = RadioState.RX

            elif command == "RADIO_DISABLE":
                self.source.set_value("RADIO_STATUS", "state", RadioState.OFF)
                self.telemetry_simulator.radio_state = RadioState.OFF
                if ("RADIO_STATUS", "state") in self._fault_original_values:
                    self._fault_original_values[("RADIO_STATUS", "state")] = RadioState.OFF

            elif command == "SDR_START_RX":
                self.source.set_value("SDR_STATUS", "status", SDRStatus.RECEIVING)
                self.telemetry_simulator.sdr_status = SDRStatus.RECEIVING

            elif command == "SDR_STOP_RX":
                self.source.set_value("SDR_STATUS", "status", SDRStatus.IDLE)
                self.telemetry_simulator.sdr_status = SDRStatus.IDLE

            elif command in {"PING", "REQUEST_STATUS"}:
                self.controller.send_once(selected_packet)

            elif command == "SET_MODE":
                mode = self.source.set_value(
                    "SPACECRAFT_POWER",
                    "obc_state",
                    parameter.upper() if parameter else "NOMINAL",
                )
                self.telemetry_simulator.spacecraft_parameters["obc_state"] = mode

        except (RuntimeError, TypeError, ValueError) as exc:
            self._append_log("ERROR", "COMMAND", str(exc))
            return

        if command.startswith("SIM_INJECT_"):
            self.metrics.record_fault_injection(command)
        if not command.startswith("SIM_"):
            self.telemetry_simulator.simulate_command_sent()

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
        timestamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
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
