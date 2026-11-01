from __future__ import annotations

import csv
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from google.protobuf.json_format import MessageToDict

from integration.backend import HardwareBackend
from integration.codec import PI_BODIES, PacketFactory, decode, encode
from packet.generated import integration_pb2 as pb


class EventLog:
    """Append each valid event to JSONL and CSV; unknown measurements stay blank."""
    FIELDS = ("local_time_unix_ms", "direction", "kind", "session_id", "sequence",
              "event_time_unix_ms", "command_id", "state", "payload_hex",
              "rssi_dbm", "snr_db", "error_code", "detail_json")

    def __init__(self, directory: str | Path | None = None):
        self.rows = []
        self._json = self._csv = None
        if directory is not None:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            basename = f"integration-{time.time_ns()}"
            self._json = (directory / f"{basename}.jsonl").open("w", encoding="utf-8")
            self._csv = (directory / f"{basename}.csv").open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._csv, fieldnames=self.FIELDS)
            self._writer.writeheader()

    def record(self, kind: str, *, direction: str = "LOCAL", packet=None, detail=""):
        row = dict.fromkeys(self.FIELDS, "")
        row.update(local_time_unix_ms=time.time_ns() // 1_000_000, direction=direction,
                   kind=kind, detail_json=json.dumps(detail, ensure_ascii=False))
        if packet is not None:
            body = getattr(packet, packet.WhichOneof("body"))
            row.update(session_id=packet.session_id, sequence=packet.sequence,
                       event_time_unix_ms=packet.timestamp_unix_ms,
                       detail_json=json.dumps(MessageToDict(packet, preserving_proto_field_name=True)))
            for field in ("command_id", "error_code"):
                if hasattr(body, field):
                    row[field] = getattr(body, field)
            if hasattr(body, "state"):
                row["state"] = pb.CommandState.Name(body.state)
            if hasattr(body, "payload"):
                row["payload_hex"] = body.payload.hex()
            for field in ("rssi_dbm", "snr_db"):
                if hasattr(body, field) and body.HasField(field):
                    row[field] = getattr(body, field)
        self.rows.append(row)
        del self.rows[:-1000]
        if self._json is not None:
            self._json.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._json.flush()
            self._writer.writerow(row)
            self._csv.flush()
        return row

    def close(self):
        if self._json is not None:
            self._json.close()
            self._csv.close()
            self._json = self._csv = None


@dataclass
class TrackedCommand:
    command_id: str
    payload: bytes
    state: str
    deadline: float
    error_code: str = ""
    error_message: str = ""


class McsController:
    def __init__(self, transport, *, log_dir=None, acceptance_timeout=2.0, completion_timeout=3.0):
        self.transport = transport
        self.factory = PacketFactory()
        self.log = EventLog(log_dir)
        self.commands = OrderedDict()
        self.status = None
        self.last_status = None
        self.peer_session = None
        self.retired_sessions = set()
        self.seen = OrderedDict()
        self.high_sequence = 0
        self.receptions = []
        self.acceptance_timeout = acceptance_timeout
        self.completion_timeout = completion_timeout
        transport.set_message_handler(self.receive)

    @property
    def fresh(self):
        return self.last_status is not None and time.monotonic() - self.last_status < 3.0

    def transmit(self, payload: bytes) -> str:
        if not self.fresh:
            raise ValueError("No current Pi Status; transmitting is disabled")
        if not payload or len(payload) > self.status.max_tx_payload_bytes:
            raise ValueError(f"Payload must be 1–{self.status.max_tx_payload_bytes} bytes")
        if not any(c.component == pb.RADIO and c.health == pb.READY for c in self.status.components):
            raise ValueError("Pi radio is not READY")
        if sum(c.state in ("SENT", "ACCEPTED") for c in self.commands.values()) >= 1024:
            raise ValueError("Too many pending commands")
        if len(self.commands) >= 10000:
            for old_id, old in list(self.commands.items()):
                if old.state not in ("SENT", "ACCEPTED"):
                    del self.commands[old_id]
                    break
        command_id = str(uuid4())
        packet = self.factory.make("transmit_request", pb.TransmitRequest(command_id=command_id, payload=payload))
        self.transport.send(encode(packet))
        self.commands[command_id] = TrackedCommand(command_id, bytes(payload), "SENT",
                                                  time.monotonic() + self.acceptance_timeout)
        self.log.record("transmit_request", direction="TX", packet=packet)
        return command_id

    def _unknown(self, command: TrackedCommand, reason: str):
        command.state = "OUTCOME_UNKNOWN"
        command.error_message = reason
        self.log.record("OUTCOME_UNKNOWN", detail={"command_id": command.command_id, "reason": reason})

    def receive(self, frame: bytes):
        try:
            packet = decode(frame)
            kind = packet.WhichOneof("body")
            if kind not in PI_BODIES:
                raise ValueError("wrong direction: MCS only accepts Pi event messages")
            if packet.session_id != self.peer_session:
                if packet.session_id in self.retired_sessions or kind != "status":
                    raise ValueError("unknown/retired Pi session; Status required first")
                if self.peer_session is not None:
                    self.retired_sessions.add(self.peer_session)
                    for command in self.commands.values():
                        if command.state in ("SENT", "ACCEPTED"):
                            self._unknown(command, "Pi restarted; no automatic replay")
                self.peer_session = packet.session_id
                self.high_sequence = 0
            key = (packet.session_id, packet.sequence)
            if key in self.seen:
                if self.seen[key][1] != frame:
                    raise ValueError("same sequence used for different data")
                self.log.record("DUPLICATE", detail={"sequence": packet.sequence})
                return
            now = time.monotonic()
            self.seen[key] = (now, frame)
            while self.seen and (len(self.seen) > 10000 or next(iter(self.seen.values()))[0] < now - 600):
                self.seen.popitem(last=False)
            if packet.sequence > self.high_sequence + 1:
                self.log.record("SEQUENCE_GAP", detail={"after": self.high_sequence, "received": packet.sequence})
            elif packet.sequence <= self.high_sequence:
                self.log.record("REORDERED", detail={"sequence": packet.sequence})
            self.high_sequence = max(self.high_sequence, packet.sequence)
            if kind == "status":
                self.status = pb.Status()
                self.status.CopyFrom(packet.status)
                self.last_status = now
                self.transport.mark_connected(True)
            elif kind == "radio_receive":
                self.receptions.append(packet)
                del self.receptions[:-1000]
            else:
                result = packet.command_result
                command = self.commands.get(result.command_id)
                if command is None:
                    raise ValueError("result for an unknown command")
                state = pb.CommandState.Name(result.state)
                if command.state in ("TX_COMPLETED", "FAILED", "REJECTED"):
                    if command.state != state:
                        raise ValueError("command state regressed or conflicting terminal result")
                else:
                    if state == "ACCEPTED" and command.state != "ACCEPTED":
                        command.deadline = now + self.completion_timeout
                    command.state = state
                    command.error_code, command.error_message = result.error_code, result.error_message
            self.log.record(kind, direction="RX", packet=packet)
        except ValueError as exc:
            self.log.record("REJECTED_FRAME", detail=str(exc))

    def tick(self):
        self.transport.poll()
        now = time.monotonic()
        if self.last_status is not None and not self.fresh:
            self.transport.mark_connected(False)
        for command in self.commands.values():
            if command.state in ("SENT", "ACCEPTED") and now >= command.deadline:
                self._unknown(command, "Response timeout; TX may have occurred")

    def close(self):
        self.transport.stop()
        self.log.close()


@dataclass
class CachedCommand:
    payload: bytes
    result: pb.CommandResult
    updated: float


class PiEngine:
    """Network-ready Pi service logic; backend is the only hardware boundary."""
    def __init__(self, transport, backend: HardwareBackend, *, log_dir=None):
        self.transport, self.backend = transport, backend
        self.factory = PacketFactory()
        self.cache = {}
        self.log = EventLog(log_dir)
        self.last_status_time = -1.0
        self.last_status_bytes = None
        transport.set_message_handler(self.receive)

    def _send(self, kind: str, body, *, timestamp_ms=None):
        packet = self.factory.make(kind, body, timestamp_ms=timestamp_ms)
        self.log.record(kind, direction="TX", packet=packet)
        try:
            self.transport.send(encode(packet))
        except ConnectionError:
            self.log.record("SEND_UNAVAILABLE", detail=kind)

    def _result(self, command_id, state, code="", message="", *, timestamp_ms=None, remember=True):
        result = pb.CommandResult(command_id=command_id, state=state, error_code=code, error_message=message)
        if remember:
            cached = self.cache[command_id]
            cached.result.CopyFrom(result)
            cached.updated = time.monotonic()
        self._send("command_result", result, timestamp_ms=timestamp_ms)

    def receive(self, frame: bytes):
        try:
            packet = decode(frame)
            if packet.WhichOneof("body") != "transmit_request":
                raise ValueError("wrong direction: Pi only accepts TransmitRequest")
            self.log.record("transmit_request", direction="RX", packet=packet)
            request = packet.transmit_request
            cached = self.cache.get(request.command_id)
            if cached is not None:
                if cached.payload != request.payload:
                    self._result(request.command_id, pb.REJECTED, "ID_CONFLICT",
                                 "Same command ID has different bytes", remember=False)
                else:
                    self._send("command_result", cached.result)
                return
            if len(self.cache) >= 4096:
                self._result(request.command_id, pb.REJECTED, "HARDWARE_BUSY",
                             "Duplicate-protection cache is full", remember=False)
                return
            self.cache[request.command_id] = CachedCommand(bytes(request.payload), pb.CommandResult(), time.monotonic())
            status = self.backend.snapshot()
            if len(request.payload) > status.max_tx_payload_bytes:
                self._result(request.command_id, pb.REJECTED, "PAYLOAD_TOO_LARGE", "Hardware TX payload limit exceeded")
            elif not any(c.component == pb.RADIO and c.health == pb.READY for c in status.components):
                self._result(request.command_id, pb.REJECTED, "HARDWARE_NOT_READY", "Radio is not READY")
            else:
                self._result(request.command_id, pb.ACCEPTED)
                try:
                    self.backend.submit_transmit(request.command_id, bytes(request.payload))
                except Exception as exc:
                    self._result(request.command_id, pb.FAILED, "TX_FAILED", str(exc))
        except ValueError as exc:
            self.log.record("REJECTED_FRAME", detail=str(exc))

    def tick(self):
        self.transport.poll()
        now = time.monotonic()
        status = self.backend.snapshot()
        serialized = status.SerializeToString(deterministic=True)
        if now - self.last_status_time >= 1.0 or serialized != self.last_status_bytes:
            self._send("status", status)
            self.last_status_time, self.last_status_bytes = now, serialized
        for event in self.backend.drain_completions():
            cached = self.cache.get(event.command_id)
            if cached is None or cached.result.state != pb.ACCEPTED:
                self.log.record("UNEXPECTED_COMPLETION", detail=event.command_id)
                continue
            self._result(event.command_id, pb.TX_COMPLETED if event.success else pb.FAILED,
                         "" if event.success else (event.error_code or "TX_FAILED"),
                         "" if event.success else event.error_message,
                         timestamp_ms=event.timestamp_ms)
        for event in self.backend.drain_received():
            body = pb.RadioReceive(payload=event.payload)
            for field in ("rssi_dbm", "snr_db", "radio_crc_ok"):
                value = getattr(event, field)
                if value is not None:
                    setattr(body, field, value)
            try:
                self._send("radio_receive", body, timestamp_ms=event.timestamp_ms)
            except ValueError as exc:
                self.log.record("NATIVE_RX_REJECTED", detail=str(exc))
        for command_id, cached in list(self.cache.items()):
            if cached.result.state != pb.ACCEPTED and now - cached.updated > 600:
                del self.cache[command_id]

    def close(self):
        self.transport.stop()
        self.log.close()
