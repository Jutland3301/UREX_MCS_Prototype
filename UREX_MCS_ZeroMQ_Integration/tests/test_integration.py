from __future__ import annotations

import sqlite3
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from integration.backend import MockBackend, Reception
from integration.codec import PacketFactory, decode, encode
from integration.engine import McsController, PiEngine
from integration.transport import ZmqTransport
from packet.generated import integration_pb2 as pb


class Collector:
    def __init__(self):
        self.messages = []
    def set_message_handler(self, handler): self.handler = handler
    def send(self, frame): self.messages.append(decode(frame))
    def mark_connected(self, connected): self.connected = connected
    def poll(self): pass
    def stop(self): pass


def request(factory, payload=b"\x00\x0a\xff", command_id=None):
    return factory.make("transmit_request", pb.TransmitRequest(
        command_id=command_id or str(uuid4()), payload=payload))


def wait_for(controller, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controller.tick()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for real ZeroMQ event")


def test_shared_golden_vector():
    factory = PacketFactory()
    factory.session_id = "00000000-0000-0000-0000-000000000001"
    status = MockBackend().snapshot()
    for c in status.components:
        c.health = pb.READY if c.component == pb.PI else pb.UNAVAILABLE
        c.configuration_summary = ""
    status.clock_synchronized = True
    packet = factory.make("status", status, timestamp_ms=1791766800000)
    frame = encode(packet)
    assert len(frame) == 94
    assert frame[-2:] == bytes.fromhex("87f0")
    assert decode(frame) == packet


@pytest.mark.parametrize("change", ["crc", "length", "version", "magic", "truncated", "oversized"])
def test_reject_bad_frames(change):
    frame = bytearray(encode(request(PacketFactory())))
    if change == "crc": frame[-1] ^= 1
    if change == "length": frame[6] ^= 1
    if change == "version": frame[2] = 2
    if change == "magic": frame[0] = 0
    if change == "truncated": frame = frame[:4]
    if change == "oversized": frame[3:7] = (65537).to_bytes(4, "big")
    with pytest.raises(ValueError): decode(bytes(frame))


def test_missing_and_nonfinite_radio_measurements():
    factory = PacketFactory()
    rx = factory.make("radio_receive", pb.RadioReceive(payload=b"\x00"))
    assert not decode(encode(rx)).radio_receive.HasField("rssi_dbm")
    with pytest.raises(ValueError):
        factory.make("radio_receive", pb.RadioReceive(payload=b"x", rssi_dbm=float("nan")))
    with pytest.raises(ValueError):
        factory.make("radio_receive", pb.RadioReceive(payload=b"x", radio_crc_ok=False))


def test_pi_idempotency_conflict_limits_and_failure():
    wire = Collector()
    backend = MockBackend(delay_s=0)
    pi = PiEngine(wire, backend)
    factory = PacketFactory()
    packet = request(factory)
    pi.receive(encode(packet))
    assert wire.messages[-1].command_result.state == pb.ACCEPTED
    pi.tick()
    assert pi.cache[packet.transmit_request.command_id].result.state == pb.TX_COMPLETED
    pi.receive(encode(packet))
    assert wire.messages[-1].command_result.state == pb.TX_COMPLETED
    assert backend.tx_count == 1
    conflict = request(factory, b"different", packet.transmit_request.command_id)
    pi.receive(encode(conflict))
    assert wire.messages[-1].command_result.error_code == "ID_CONFLICT"
    assert pi.cache[packet.transmit_request.command_id].result.state == pb.TX_COMPLETED
    pi.receive(encode(request(factory, b"x" * 64)))
    assert wire.messages[-1].command_result.error_code == "PAYLOAD_TOO_LARGE"
    assert backend.tx_count == 1
    backend.mode = "fail"
    pi.receive(encode(request(factory)))
    pi.tick()
    assert any(p.WhichOneof("body") == "command_result" and p.command_result.state == pb.FAILED
               for p in wire.messages)


def test_native_bad_rx_and_unavailable_radio():
    class NotReady(MockBackend):
        def snapshot(self):
            result = super().snapshot()
            result.components[1].health = pb.INITIALIZING
            return result
    wire = Collector()
    backend = NotReady()
    pi = PiEngine(wire, backend)
    pi.receive(encode(request(PacketFactory())))
    assert wire.messages[-1].command_result.error_code == "HARDWARE_NOT_READY"
    assert backend.tx_count == 0
    backend.received.append(Reception(b"bad", 1234, radio_crc_ok=False))
    pi.tick()
    assert pi.log.rows[-1]["kind"] == "NATIVE_RX_REJECTED"


def test_mcs_timeout_restart_dedupe_and_blank_logs(tmp_path):
    wire = Collector()
    mcs = McsController(wire, log_dir=tmp_path, acceptance_timeout=0)
    factory = PacketFactory()
    mcs.receive(encode(factory.make("status", MockBackend().snapshot())))
    cmd = mcs.transmit(b"binary\x00\x0a")
    mcs.tick()
    assert mcs.commands[cmd].state == "OUTCOME_UNKNOWN"
    late = factory.make("command_result", pb.CommandResult(command_id=cmd, state=pb.TX_COMPLETED))
    mcs.receive(encode(late))
    assert mcs.commands[cmd].state == "TX_COMPLETED"
    cmd2 = mcs.transmit(b"next")
    old_status = encode(factory.make("status", MockBackend().snapshot()))
    new = PacketFactory()
    mcs.receive(encode(new.make("status", MockBackend().snapshot())))
    assert mcs.commands[cmd2].state == "OUTCOME_UNKNOWN"
    mcs.receive(old_status)
    assert mcs.peer_session == new.session_id
    rx = encode(new.make("radio_receive", pb.RadioReceive(payload=b"\x00\x0a\xff")))
    mcs.receive(rx)
    mcs.receive(rx)
    assert len(mcs.receptions) == 1
    mcs.last_status = time.monotonic() - 4
    with pytest.raises(ValueError): mcs.transmit(b"x")
    mcs.close()
    rows = [json.loads(x) for x in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    row = next(r for r in rows if r["kind"] == "radio_receive")
    assert row["payload_hex"] == "000aff" and row["rssi_dbm"] == "" and row["snr_db"] == ""
    with sqlite3.connect(next(tmp_path.glob("*.db"))) as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == len(rows)


@pytest.mark.parametrize("completion_at", [2.9, None, 3.2])
def test_default_completion_timeout_boundary_and_late_result(monkeypatch, completion_at):
    clock = [100.0]
    monkeypatch.setattr("integration.engine.time.monotonic", lambda: clock[0])
    wire = Collector()
    mcs = McsController(wire)
    factory = PacketFactory()
    mcs.receive(encode(factory.make("status", MockBackend().snapshot())))
    cmd = mcs.transmit(b"timeout-boundary")
    # Acceptance starts the completion timer, independently of the send time.
    clock[0] = 101.0
    mcs.receive(encode(factory.make("command_result", pb.CommandResult(
        command_id=cmd, state=pb.ACCEPTED))))
    assert mcs.commands[cmd].deadline == 104.0
    clock[0] = 103.9
    mcs.tick()
    assert mcs.commands[cmd].state == "ACCEPTED"
    if completion_at == 2.9:
        mcs.receive(encode(factory.make("command_result", pb.CommandResult(
            command_id=cmd, state=pb.TX_COMPLETED))))
    clock[0] = 104.0
    mcs.tick()
    assert mcs.commands[cmd].state == (
        "TX_COMPLETED" if completion_at == 2.9 else "OUTCOME_UNKNOWN")
    if completion_at == 3.2:
        clock[0] = 104.2
        mcs.receive(encode(factory.make("command_result", pb.CommandResult(
            command_id=cmd, state=pb.TX_COMPLETED))))
        assert mcs.commands[cmd].state == "TX_COMPLETED"
    assert len(wire.messages) == 1  # Timeout must never trigger another transmission.
    mcs.close()


@pytest.mark.parametrize("mode, expected", [("success", "TX_COMPLETED"), ("fail", "FAILED"),
                                            ("timeout", "OUTCOME_UNKNOWN")])
@pytest.mark.parametrize("implementation", ["python", "cpp"])
def test_real_tcp_separate_mock_process(tmp_path, mode, expected, implementation):
    # Wildcard bind avoids this runner's denied interface-enumeration syscall.
    wire = ZmqTransport("tcp://*:0")
    mcs = McsController(wire, log_dir=tmp_path / "mcs", completion_timeout=0.15)
    wire.start()
    endpoint = wire.bound_endpoint.replace("0.0.0.0", "127.0.0.1")
    root = Path(__file__).resolve().parents[1]
    if implementation == "cpp":
        binary = root / "pi_service/build/mock_pi_cpp"
        if not binary.exists():
            mcs.close()
            pytest.skip("build C++ mock with make -C pi_service to run cross-language checks")
        command = [str(binary), "--connect", endpoint, "--mode", mode]
    else:
        command = [sys.executable, "-m", "integration.mock_pi", "--connect", endpoint,
                   "--mode", mode, "--log-dir", str(tmp_path / "pi")]
    process = subprocess.Popen(command,
                               cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        wait_for(mcs, lambda: mcs.fresh)
        cmd = mcs.transmit(b"\x00\x0a\xff")
        wait_for(mcs, lambda: mcs.commands[cmd].state == expected)
        if mode == "success":
            wait_for(mcs, lambda: bool(mcs.receptions))
            assert mcs.receptions[-1].radio_receive.payload == b"\x00\x0a\xff"
            # New ZeroMQ envelope/sequence, same command ID: still only one native TX.
            duplicate = mcs.factory.make("transmit_request", pb.TransmitRequest(command_id=cmd, payload=b"\x00\x0a\xff"))
            wire.send(encode(duplicate))
            wait_for(mcs, lambda: sum(r["kind"] == "command_result" for r in mcs.log.rows) >= 3)
            assert len(mcs.receptions) == 1
        pending = mcs.transmit(b"unconfirmed") if mode == "success" else None
        process.terminate()
        process.wait(timeout=3)
        if mode == "success":
            old_session = mcs.peer_session
            process = subprocess.Popen(command,
                                       cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            wait_for(mcs, lambda: mcs.peer_session != old_session)
            if pending:
                assert mcs.commands[pending].state == "OUTCOME_UNKNOWN"
    finally:
        if process.poll() is None:
            process.terminate()
        stdout, stderr = process.communicate(timeout=3)
        mcs.close()
        assert process.returncode == 0, (stdout, stderr)


def test_network_gui_with_mock(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from gui.integration_window import IntegrationWindow
    app = QApplication.instance() or QApplication([])
    window = IntegrationWindow("tcp://*:0", str(tmp_path))
    pi_wire = ZmqTransport(window.transport.bound_endpoint.replace("0.0.0.0", "127.0.0.1"), pi=True)
    pi = PiEngine(pi_wire, MockBackend(delay_s=0))
    pi_wire.start()
    try:
        deadline = time.monotonic() + 4
        while not window.send_button.isEnabled() and time.monotonic() < deadline:
            pi.tick(); window.tick(); app.processEvents(); time.sleep(0.01)
        assert window.send_button.isEnabled()
        window.payload.setText("00 0A FF")
        window.send_payload()
        deadline = time.monotonic() + 4
        while window.rx_table.rowCount() == 0 and time.monotonic() < deadline:
            pi.tick(); window.tick(); app.processEvents(); time.sleep(0.01)
        assert window.status_table.rowCount() == 5
        assert window.command_table.item(0, 1).text() == "TX_COMPLETED"
        assert window.rx_table.item(0, 2).text() == "000aff"
    finally:
        pi.close()
        window.close()
