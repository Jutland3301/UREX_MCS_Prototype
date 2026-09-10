from __future__ import annotations

import heapq
import random
import time
from collections.abc import Callable

from communication.base_transport import BaseTransport, TransportStatus
from simulator.scenario_config import NetworkConditions

TransportEventHandler = Callable[[str, int, float], None]


class SimulatedTransport(BaseTransport):
    """In-process transport with controllable loss, corruption and latency."""

    def __init__(
        self,
        conditions: NetworkConditions | None = None,
        *,
        random_seed: int = 3301,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__("SIMULATOR-IMPAIRED-BINARY")
        self.conditions = conditions or NetworkConditions()
        self.conditions.validate()
        self._random = random.Random(random_seed)
        self._monotonic = monotonic
        self._queue: list[tuple[float, int, float, bytes]] = []
        self._queue_order = 0
        self._event_handler: TransportEventHandler | None = None
        self.sent_messages: list[bytes] = []

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    def set_event_handler(self, handler: TransportEventHandler | None) -> None:
        self._event_handler = handler

    def configure(self, conditions: NetworkConditions) -> None:
        conditions.validate()
        self.conditions = conditions

    def start(self) -> None:
        self._set_status(TransportStatus.CONNECTED)

    def stop(self) -> None:
        for _, _, _, raw in self._queue:
            self._emit_event("dropped", len(raw), 0.0)
        self._queue.clear()
        self._set_status(TransportStatus.STOPPED)

    def reset_queue(self) -> None:
        self._queue.clear()

    def send(self, message: bytes) -> None:
        if self.status != TransportStatus.CONNECTED:
            raise RuntimeError("transport is not connected")
        self.sent_messages.append(bytes(message))

    def submit_incoming(
        self,
        message: bytes,
        *,
        force_drop: bool = False,
        force_corrupt: bool = False,
        delay_override_ms: float | None = None,
    ) -> str:
        if self.status != TransportStatus.CONNECTED:
            raise RuntimeError("transport is not connected")

        raw = bytes(message)
        drop = force_drop or self._chance(self.conditions.drop_rate_percent)
        if drop:
            self._emit_event("dropped", len(raw), 0.0)
            return "dropped"

        corrupt = force_corrupt or self._chance(
            self.conditions.corruption_rate_percent
        )
        if corrupt and raw:
            damaged = bytearray(raw)
            damaged[self._random.randrange(len(damaged))] ^= 0x01
            raw = bytes(damaged)
            self._emit_event("corrupted", len(raw), 0.0)

        base_delay_ms = (
            self.conditions.delay_ms
            if delay_override_ms is None
            else max(0.0, float(delay_override_ms))
        )
        jitter_ms = self._random.uniform(
            -self.conditions.jitter_ms,
            self.conditions.jitter_ms,
        )
        effective_delay_ms = max(0.0, base_delay_ms + jitter_ms)
        submitted_at = self._monotonic()
        due_at = submitted_at + effective_delay_ms / 1000.0
        self._queue_order += 1
        heapq.heappush(
            self._queue,
            (due_at, self._queue_order, submitted_at, raw),
        )
        self._emit_event("scheduled", len(raw), effective_delay_ms)
        return "corrupted" if corrupt else "scheduled"

    def poll(self, now: float | None = None) -> int:
        if self.status != TransportStatus.CONNECTED:
            return 0
        now = self._monotonic() if now is None else now
        delivered = 0
        while self._queue and self._queue[0][0] <= now:
            _, _, submitted_at, raw = heapq.heappop(self._queue)
            latency_ms = max(0.0, (now - submitted_at) * 1000.0)
            self._emit_message(raw)
            self._emit_event("delivered", len(raw), latency_ms)
            delivered += 1
        return delivered

    def feed_incoming(self, message: bytes) -> None:
        self.submit_incoming(message)
        self.poll()

    def _chance(self, percent: float) -> bool:
        return self._random.random() * 100.0 < float(percent)

    def _emit_event(self, event: str, size: int, latency_ms: float) -> None:
        if self._event_handler is not None:
            self._event_handler(event, size, latency_ms)
