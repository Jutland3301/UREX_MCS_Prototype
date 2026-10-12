from __future__ import annotations

from dataclasses import asdict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from measurement.metrics_collector import MetricsSnapshot
from simulator.scenario_controller import ExperimentState


class ExperimentPanel(QWidget):
    start_requested = Signal(float, int)
    pause_resume_requested = Signal()
    stop_requested = Signal()
    export_requested = Signal(str)

    def __init__(self, duration_s: float, burst_size: int) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.addWidget(self._build_controls(duration_s, burst_size))
        root.addWidget(self._build_results())
        root.addStretch(1)

    def update_state(self, state: ExperimentState) -> None:
        self.state_label.setText(state.value)
        self.pause_button.setText(
            "Resume" if state == ExperimentState.PAUSED else "Pause"
        )

    def update_metrics(self, snapshot: MetricsSnapshot) -> None:
        values = asdict(snapshot)
        formats = {
            "elapsed_s": "{:.2f} s",
            "packets_per_second": "{:.2f} packet/s",
            "bytes_per_second": "{:.2f} byte/s",
            "average_packet_size": "{:.2f} byte",
            "average_delivery_delay_ms": "{:.2f} ms",
            "maximum_delivery_delay_ms": "{:.2f} ms",
        }
        for name, label in self.metric_labels.items():
            value = values[name]
            if isinstance(value, dict):
                label.setText(str(sum(value.values())))
            else:
                label.setText(formats.get(name, "{}").format(value))

    def _build_controls(self, duration_s: float, burst_size: int) -> QGroupBox:
        group = QGroupBox("Experiment Control")
        form = QFormLayout(group)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 86_400.0)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setValue(duration_s)
        self.burst_spin = QSpinBox()
        self.burst_spin.setRange(1, 10_000)
        self.burst_spin.setValue(burst_size)

        buttons = QHBoxLayout()
        start_button = QPushButton("Start")
        start_button.clicked.connect(
            lambda: self.start_requested.emit(
                self.duration_spin.value(), self.burst_spin.value()
            )
        )
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_resume_requested.emit)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_requested.emit)
        buttons.addWidget(start_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(stop_button)

        self.state_label = QLabel(ExperimentState.STOPPED.value)
        form.addRow("Duration", self.duration_spin)
        form.addRow("Burst per due packet", self.burst_spin)
        form.addRow("State", self.state_label)
        form.addRow(buttons)
        return group

    def _build_results(self) -> QGroupBox:
        group = QGroupBox("Live Measurements")
        form = QFormLayout(group)
        metric_names = (
            ("elapsed_s", "Elapsed"),
            ("generated_packets", "Generated packets"),
            ("delivered_packets", "Delivered packets"),
            ("dropped_packets", "Dropped packets"),
            ("corrupted_packets", "Corrupted packets"),
            ("parse_ok_packets", "Parser OK"),
            ("parse_error_packets", "Parser errors"),
            ("fault_injections", "Fault commands issued"),
            ("equipment_fault_packet_total", "Equipment fault packets"),
            ("queue_depth", "Delayed queue depth"),
            ("packets_per_second", "Throughput"),
            ("bytes_per_second", "Byte rate"),
            ("minimum_packet_size", "Minimum packet size"),
            ("average_packet_size", "Average packet size"),
            ("maximum_packet_size", "Maximum packet size"),
            ("average_delivery_delay_ms", "Average delivery delay"),
            ("maximum_delivery_delay_ms", "Maximum delivery delay"),
        )
        self.metric_labels: dict[str, QLabel] = {}
        for name, display_name in metric_names:
            label = QLabel("0")
            self.metric_labels[name] = label
            form.addRow(display_name, label)

        exports = QHBoxLayout()
        json_button = QPushButton("Export JSON")
        csv_button = QPushButton("Export CSV")
        json_button.clicked.connect(lambda: self.export_requested.emit("json"))
        csv_button.clicked.connect(lambda: self.export_requested.emit("csv"))
        exports.addWidget(json_button)
        exports.addWidget(csv_button)
        form.addRow(exports)
        return group
