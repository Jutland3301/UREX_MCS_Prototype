from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from simulator.manual_packet_source import ManualPacketSource
from simulator.scenario_config import NetworkConditions


class SimulatorControlPanel(QWidget):
    """Manual packet, telemetry and network-condition controls."""

    field_update_requested = Signal(str, str, str)
    period_update_requested = Signal(str, float)
    send_once_requested = Signal(str, bool, bool)
    raw_packet_requested = Signal(str)
    network_update_requested = Signal(float, float, float, float)
    save_scenario_requested = Signal()

    def __init__(self, source: ManualPacketSource) -> None:
        super().__init__()
        self.source = source
        root = QVBoxLayout(self)
        root.addWidget(self._build_telemetry_editor())
        root.addWidget(self._build_network_editor())
        root.addWidget(self._build_raw_editor())
        root.addStretch(1)
        self._packet_changed(self.packet_combo.currentText())

    @property
    def selected_packet_name(self) -> str:
        return self.packet_combo.currentText()

    def set_message(self, message: str, error: bool = False) -> None:
        self.message_label.setText(message)
        self.message_label.setStyleSheet("color: #b00020;" if error else "")

    def set_network_conditions(self, conditions: NetworkConditions) -> None:
        self.drop_spin.setValue(conditions.drop_rate_percent)
        self.corrupt_spin.setValue(conditions.corruption_rate_percent)
        self.delay_spin.setValue(conditions.delay_ms)
        self.jitter_spin.setValue(conditions.jitter_ms)

    def refresh_current_value(self) -> None:
        packet_name = self.packet_combo.currentText()
        field_name = self.field_combo.currentText()
        if packet_name and field_name:
            value = self.source.get_value(packet_name, field_name)
            self.value_edit.setText(self._display_value(value))
            field = next(
                field
                for field in self.source.definition(packet_name).fields
                if field.name == field_name
            )
            self.unit_label.setText(field.unit or "-")

    def _build_telemetry_editor(self) -> QGroupBox:
        group = QGroupBox("Manual Telemetry Packet")
        layout = QGridLayout(group)

        self.packet_combo = QComboBox()
        self.field_combo = QComboBox()
        self.value_edit = QLineEdit()
        self.unit_label = QLabel("-")

        self.period_spin = QDoubleSpinBox()
        self.period_spin.setRange(0.01, 3600.0)
        self.period_spin.setDecimals(3)
        self.period_spin.setSuffix(" s")

        self.packet_combo.addItems(self.source.packet_names)
        self.packet_combo.currentTextChanged.connect(self._packet_changed)
        self.field_combo.currentTextChanged.connect(
            lambda _text: self.refresh_current_value()
        )

        apply_button = QPushButton("Apply Value / Period")
        apply_button.clicked.connect(self._request_field_update)
        send_button = QPushButton("Send Once")
        send_button.clicked.connect(
            lambda: self.send_once_requested.emit(
                self.selected_packet_name, False, False
            )
        )
        corrupt_button = QPushButton("Send Corrupted Once")
        corrupt_button.clicked.connect(
            lambda: self.send_once_requested.emit(
                self.selected_packet_name, False, True
            )
        )
        drop_button = QPushButton("Drop Once")
        drop_button.clicked.connect(
            lambda: self.send_once_requested.emit(
                self.selected_packet_name, True, False
            )
        )
        save_button = QPushButton("Save Scenario")
        save_button.clicked.connect(self.save_scenario_requested.emit)

        layout.addWidget(QLabel("Packet"), 0, 0)
        layout.addWidget(self.packet_combo, 0, 1)
        layout.addWidget(QLabel("Field"), 0, 2)
        layout.addWidget(self.field_combo, 0, 3)
        layout.addWidget(QLabel("Value"), 1, 0)
        layout.addWidget(self.value_edit, 1, 1, 1, 2)
        layout.addWidget(self.unit_label, 1, 3)
        layout.addWidget(QLabel("Update period"), 2, 0)
        layout.addWidget(self.period_spin, 2, 1)
        layout.addWidget(apply_button, 2, 2, 1, 2)
        layout.addWidget(send_button, 3, 0)
        layout.addWidget(corrupt_button, 3, 1)
        layout.addWidget(drop_button, 3, 2)
        layout.addWidget(save_button, 3, 3)
        return group

    def _build_network_editor(self) -> QGroupBox:
        group = QGroupBox("Network Conditions")
        layout = QFormLayout(group)

        self.drop_spin = self._condition_spin(" %", 0.0, 100.0)
        self.corrupt_spin = self._condition_spin(" %", 0.0, 100.0)
        self.delay_spin = self._condition_spin(" ms", 0.0, 60_000.0)
        self.jitter_spin = self._condition_spin(" ms", 0.0, 60_000.0)
        apply_button = QPushButton("Apply Network Conditions")
        apply_button.clicked.connect(
            lambda: self.network_update_requested.emit(
                self.drop_spin.value(),
                self.corrupt_spin.value(),
                self.delay_spin.value(),
                self.jitter_spin.value(),
            )
        )

        layout.addRow("Drop rate", self.drop_spin)
        layout.addRow("Corruption rate", self.corrupt_spin)
        layout.addRow("Fixed delay", self.delay_spin)
        layout.addRow("Delay jitter (+/-)", self.jitter_spin)
        layout.addRow(apply_button)
        return group

    def _build_raw_editor(self) -> QGroupBox:
        group = QGroupBox("Raw Packet Input")
        layout = QVBoxLayout(group)
        self.raw_hex_edit = QPlainTextEdit()
        self.raw_hex_edit.setPlaceholderText(
            "Paste hexadecimal bytes, for example: 55 58 01 ..."
        )
        self.raw_hex_edit.setMaximumHeight(90)
        send_button = QPushButton("Send Raw Hex")
        send_button.clicked.connect(
            lambda: self.raw_packet_requested.emit(
                self.raw_hex_edit.toPlainText()
            )
        )
        self.message_label = QLabel("Ready")
        layout.addWidget(self.raw_hex_edit)
        layout.addWidget(send_button)
        layout.addWidget(self.message_label)
        return group

    def _packet_changed(self, packet_name: str) -> None:
        self.field_combo.clear()
        if not packet_name:
            return
        self.field_combo.addItems(self.source.field_names(packet_name))
        self.period_spin.setValue(self.source.get_period_s(packet_name))
        self.refresh_current_value()

    def _request_field_update(self) -> None:
        packet_name = self.packet_combo.currentText()
        self.field_update_requested.emit(
            packet_name,
            self.field_combo.currentText(),
            self.value_edit.text(),
        )
        self.period_update_requested.emit(packet_name, self.period_spin.value())

    @staticmethod
    def _condition_spin(
        suffix: str,
        minimum: float,
        maximum: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _display_value(value: object) -> str:
        return str(value.value if hasattr(value, "value") else value)
