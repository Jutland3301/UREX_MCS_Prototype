from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
)
from PySide6.QtCore import QTimer

from simulator.telemetry_simulator import TelemetrySimulator


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("UREX MCS Prototype")
        self.resize(500, 300)

        self.simulator = TelemetrySimulator()

        self.temperature_label = QLabel("Temperature: -- °C")
        self.voltage_label = QLabel("Voltage: -- V")
        self.rssi_label = QLabel("RSSI: -- dBm")
        self.packet_label = QLabel("Packet Count: 0")

        layout = QVBoxLayout()
        layout.addWidget(self.temperature_label)
        layout.addWidget(self.voltage_label)
        layout.addWidget(self.rssi_label)
        layout.addWidget(self.packet_label)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_telemetry)
        self.timer.start(1000)

    def update_telemetry(self):
        data = self.simulator.generate()

        self.temperature_label.setText(
            f"Temperature: {data['temperature']} °C"
        )
        self.voltage_label.setText(
            f"Voltage: {data['voltage']} V"
        )
        self.rssi_label.setText(
            f"RSSI: {data['rssi']} dBm"
        )
        self.packet_label.setText(
            f"Packet Count: {data['packet_count']}"
        )
