"""Typed boundary for native TX/RX workers; no serial/SPI driver is guessed."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from packet.generated import integration_pb2 as pb


@dataclass(frozen=True)
class Completion:
    command_id: str
    success: bool
    timestamp_ms: int
    error_code: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class Reception:
    payload: bytes
    timestamp_ms: int
    rssi_dbm: float | None = None
    snr_db: float | None = None
    radio_crc_ok: bool | None = None
    modem_config: pb.ModemConfiguration | None = None

    def __post_init__(self):
        # A later change to the backend's active settings must not mutate this RX.
        if self.modem_config is not None:
            snapshot = pb.ModemConfiguration()
            snapshot.CopyFrom(self.modem_config)
            object.__setattr__(self, "modem_config", snapshot)


class HardwareBackend(Protocol):
    def snapshot(self) -> pb.Status: ...
    def submit_transmit(self, command_id: str, payload: bytes) -> None:
        """Enqueue without blocking; completion arrives via drain_completions."""
        ...
    def drain_completions(self) -> list[Completion]: ...
    def drain_received(self) -> list[Reception]: ...


class MockBackend:
    """Synthetic bench echo for tests, never a claim about native radio success."""
    def __init__(self, *, limit: int = 63, mode: str = "success", delay_s: float = 0.05):
        self.limit, self.mode, self.delay_s = limit, mode, delay_s
        self.tx_count = 0
        self.pending = []
        self.received = []

    def snapshot(self) -> pb.Status:
        status = pb.Status(max_tx_payload_bytes=self.limit, clock_synchronized=False)
        for component in range(1, 6):
            status.components.add(component=component,
                                  health=pb.READY if component in (pb.PI, pb.RADIO)
                                  else pb.UNAVAILABLE,
                                  configuration_summary="MOCK ONLY — no hardware")
        return status

    def submit_transmit(self, command_id: str, payload: bytes) -> None:
        self.tx_count += 1
        self.pending.append((time.monotonic() + self.delay_s, command_id, bytes(payload)))

    def drain_completions(self) -> list[Completion]:
        now = time.monotonic()
        result = []
        pending = []
        for deadline, command_id, payload in self.pending:
            if now < deadline or self.mode == "timeout":
                pending.append((deadline, command_id, payload))
                continue
            timestamp = time.time_ns() // 1_000_000
            ok = self.mode == "success"
            result.append(Completion(command_id, ok, timestamp,
                                     "" if ok else "TX_FAILED",
                                     "" if ok else "Synthetic TX failure"))
            if ok:
                self.received.append(Reception(payload, timestamp, -54.0, 11.0, True,
                    pb.ModemConfiguration(frequency_hz=2400000000, spreading_factor=7,
                        bandwidth_hz=125000, coding_rate="4/5", modulation="LoRa", radio_id="MOCK")))
        self.pending = pending
        return result

    def drain_received(self) -> list[Reception]:
        result, self.received = self.received, []
        return result
