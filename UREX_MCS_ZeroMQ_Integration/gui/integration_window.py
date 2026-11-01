"""ZeroMQ monitor uses actual Pi events, without simulator fault controls."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from integration.worker import ControllerView
from packet.generated import integration_pb2 as pb


def populate(table, rows):
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            table.setItem(i, j, QTableWidgetItem(str(value)))


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    result.setWordWrap(False)
    result.horizontalHeader().setStretchLastSection(True)
    return result


class IntegrationWindow(QMainWindow):
    def __init__(self, endpoint="tcp://127.0.0.1:5557", log_dir="logs/mcs"):
        super().__init__()
        self.setWindowTitle("UREX MCS — ZeroMQ Integration")
        self.resize(1100, 720)
        self.controller = ControllerView(endpoint, log_dir, self)
        self.transport = self.controller.transport
        self._render_key = None
        self._closed = False
        self._next_render = 0.0
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel(f"MCS listen: {endpoint}    |    Logs: {log_dir}"))
        self.connection_label = QLabel("Waiting for Pi Status")
        layout.addWidget(self.connection_label)
        self.warning = QLabel("Only reported hardware values are displayed. MOCK peers are labelled in configuration.")
        layout.addWidget(self.warning)
        self.status_table = table(["Component", "Health", "Error", "Configuration"])
        for column, width in enumerate((130, 145, 160)):
            self.status_table.setColumnWidth(column, width)
        layout.addWidget(self.status_table)
        row = QHBoxLayout()
        self.payload = QLineEdit()
        self.payload.setPlaceholderText("Payload, e.g. 00 0A FF in Hex mode")
        self.format = QComboBox()
        self.format.addItems(["Hex", "UTF-8"])
        self.send_button = QPushButton("Transmit payload")
        self.send_button.clicked.connect(self.send_payload)
        row.addWidget(self.payload, 1)
        row.addWidget(self.format)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        tabs = QTabWidget()
        self.command_table = table(["Command ID", "State", "Payload hex", "Error / detail"])
        self.rx_table = table(["Pi event time (UTC ms)", "MCS receive time (UTC ms)", "Payload hex", "RSSI dBm", "SNR dB", "Modem configuration", "Config source"])
        self.event_table = table(["MCS time (UTC ms)", "Direction", "Event", "Detail"])
        for widget, widths in ((self.command_table, (300, 170, 180)),
                               (self.rx_table, (185, 185, 250, 110)),
                               (self.event_table, (185, 80, 190))):
            for column, width in enumerate(widths):
                widget.setColumnWidth(column, width)
        tabs.addTab(self.command_table, "Commands")
        tabs.addTab(self.rx_table, "Received payloads")
        tabs.addTab(self.event_table, "Packet / error log")
        layout.addWidget(tabs, 1)
        self.setCentralWidget(root)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)
        self.tick()

    def send_payload(self):
        try:
            payload = (bytes.fromhex(self.payload.text()) if self.format.currentText() == "Hex"
                       else self.payload.text().encode("utf-8"))
            self.controller.transmit(payload)
            self.refresh()
        except (ValueError, ConnectionError) as exc:
            QMessageBox.warning(self, "Transmit request not sent", str(exc))

    def tick(self):
        try:
            self.controller.tick()
        except RuntimeError as exc:
            self.connection_label.setText(f"MCS worker error: {exc}")
            self.send_button.setEnabled(False)
            return
        self.refresh()

    def refresh(self):
        if time.monotonic() < self._next_render:
            return
        self._next_render = time.monotonic() + .1
        controller = self.controller
        fresh = controller.fresh
        self.send_button.setEnabled(fresh and controller.status is not None and
                                    any(c.component == pb.RADIO and c.health == pb.READY
                                        for c in controller.status.components))
        if controller.status is None:
            self.connection_label.setText("WAITING — no valid Pi Status")
        else:
            status = controller.status
            self.connection_label.setText(
                f"{'CONNECTED' if fresh else 'STALE / DISCONNECTED'} | TX payload limit: "
                f"{status.max_tx_payload_bytes} bytes | Pi clock synchronized: {status.clock_synchronized}")
        key = (len(controller.log.rows), controller.log.rows[-1]["local_time_unix_ms"]
               if controller.log.rows else 0, fresh)
        if key == self._render_key:
            return
        self._render_key = key
        if controller.status is not None:
            populate(self.status_table, [(pb.Component.Name(c.component), pb.Health.Name(c.health),
                                         f"{c.error_code} {c.error_message}".strip(), c.configuration_summary)
                                        for c in controller.status.components])
        populate(self.command_table, [(c.command_id, c.state, c.payload.hex(),
                                       f"{c.error_code} {c.error_message}".strip())
                                      for c in list(controller.commands.values())[-200:]])
        received = [r for r in controller.log.rows if r["kind"] == "radio_receive"][-200:]
        populate(self.rx_table, [(r["event_time_unix_ms"], r["local_time_unix_ms"],
                                 r["payload_hex"], r["rssi_dbm"], r["snr_db"],
                                 r["modem_config_summary"], r["modem_config_source"])
                                for r in received])
        populate(self.event_table, [(r["local_time_unix_ms"], r["direction"], r["kind"],
                                    r["detail_json"]) for r in controller.log.rows[-200:]])

    def closeEvent(self, event):
        if not self._closed:
            self.timer.stop()
            self.controller.close()
            self._closed = True
        super().closeEvent(event)
