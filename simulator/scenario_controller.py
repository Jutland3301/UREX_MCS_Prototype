from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum

from communication.simulated_transport import SimulatedTransport
from measurement.metrics_collector import MetricsCollector
from packet.encoder import PacketEncoder
from simulator.manual_packet_source import ManualPacketSource


class ExperimentState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class ScenarioController:
    """Coordinate scheduling, manual injection, impairment and measurement."""

    def __init__(
        self,
        source: ManualPacketSource,
        encoder: PacketEncoder,
        transport: SimulatedTransport,
        metrics: MetricsCollector,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.encoder = encoder
        self.transport = transport
        self.metrics = metrics
        self._monotonic = monotonic
        self.state = ExperimentState.STOPPED
        self.duration_s = 60.0
        self.burst_size = 1
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total_s = 0.0

    @property
    def elapsed_s(self) -> float:
        if self._started_at is None:
            return 0.0
        end = self._paused_at if self._paused_at is not None else self._monotonic()
        return max(0.0, end - self._started_at - self._paused_total_s)

    def start(self, duration_s: float, burst_size: int = 1) -> None:
        if duration_s <= 0.0:
            raise ValueError("duration must be positive")
        if burst_size <= 0:
            raise ValueError("burst size must be positive")
        if self.transport.status.value != "CONNECTED":
            self.transport.start()
        self.transport.reset_queue()
        self.source.reset_schedule()
        self.metrics.start()
        self.duration_s = float(duration_s)
        self.burst_size = int(burst_size)
        self._started_at = self._monotonic()
        self._paused_at = None
        self._paused_total_s = 0.0
        self.state = ExperimentState.RUNNING

    def pause(self) -> None:
        if self.state == ExperimentState.RUNNING:
            self._paused_at = self._monotonic()
            self.metrics.pause()
            self.state = ExperimentState.PAUSED

    def resume(self) -> None:
        if self.state == ExperimentState.PAUSED and self._paused_at is not None:
            self._paused_total_s += self._monotonic() - self._paused_at
            self._paused_at = None
            self.metrics.resume()
            self.state = ExperimentState.RUNNING

    def stop(self, completed: bool = False) -> None:
        self.metrics.stop()
        self._paused_at = None
        self.state = (
            ExperimentState.COMPLETED if completed else ExperimentState.STOPPED
        )

    def tick(self) -> None:
        now = self._monotonic()
        if self.state == ExperimentState.RUNNING:
            if self.elapsed_s + 1e-9 >= self.duration_s:
                self.stop(completed=True)
            else:
                for packet_name in self.source.due_packet_names(now):
                    for _ in range(self.burst_size):
                        self._submit(self.source.encode_once(packet_name, self.encoder))
        self.transport.poll(now)

    def send_once(
        self,
        packet_name: str,
        *,
        force_drop: bool = False,
        force_corrupt: bool = False,
        delay_override_ms: float | None = None,
    ) -> str:
        raw = self.source.encode_once(packet_name, self.encoder)
        result = self._submit(
            raw,
            force_drop=force_drop,
            force_corrupt=force_corrupt,
            delay_override_ms=delay_override_ms,
        )
        self.transport.poll()
        return result

    def send_raw_hex(self, text: str) -> str:
        raw = self.source.decode_raw_hex(text)
        result = self._submit(raw)
        self.transport.poll()
        return result

    def _submit(self, raw: bytes, **kwargs: object) -> str:
        self.metrics.record_generated(raw)
        return self.transport.submit_incoming(raw, **kwargs)
