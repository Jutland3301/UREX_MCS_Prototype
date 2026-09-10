from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from packet.parser import ParseResult


@dataclass(frozen=True)
class MetricsSnapshot:
    elapsed_s: float
    generated_packets: int
    generated_bytes: int
    delivered_packets: int
    delivered_bytes: int
    dropped_packets: int
    corrupted_packets: int
    parse_ok_packets: int
    parse_error_packets: int
    queue_depth: int
    packets_per_second: float
    bytes_per_second: float
    minimum_packet_size: int
    average_packet_size: float
    maximum_packet_size: int
    average_delivery_delay_ms: float
    maximum_delivery_delay_ms: float


class MetricsCollector:
    """Collect measurements without depending on PySide6 or the GUI."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self.reset()

    def reset(self) -> None:
        self.started_at: float | None = None
        self.stopped_at: float | None = None
        self.paused_at: float | None = None
        self.paused_total_s = 0.0
        self.generated_packets = 0
        self.generated_bytes = 0
        self.delivered_packets = 0
        self.delivered_bytes = 0
        self.dropped_packets = 0
        self.corrupted_packets = 0
        self.parse_ok_packets = 0
        self.parse_error_packets = 0
        self.packet_sizes: list[int] = []
        self.delivery_delays_ms: list[float] = []

    def start(self) -> None:
        self.reset()
        self.started_at = self._monotonic()

    def stop(self) -> None:
        if self.started_at is not None and self.stopped_at is None:
            self.stopped_at = (
                self.paused_at if self.paused_at is not None else self._monotonic()
            )

    def pause(self) -> None:
        if (
            self.started_at is not None
            and self.stopped_at is None
            and self.paused_at is None
        ):
            self.paused_at = self._monotonic()

    def resume(self) -> None:
        if self.paused_at is not None:
            self.paused_total_s += self._monotonic() - self.paused_at
            self.paused_at = None

    def record_generated(self, message: bytes) -> None:
        self._ensure_started()
        size = len(message)
        self.generated_packets += 1
        self.generated_bytes += size
        self.packet_sizes.append(size)

    def record_transport_event(
        self,
        event: str,
        size: int,
        latency_ms: float,
    ) -> None:
        self._ensure_started()
        if event == "dropped":
            self.dropped_packets += 1
        elif event == "corrupted":
            self.corrupted_packets += 1
        elif event == "delivered":
            self.delivered_packets += 1
            self.delivered_bytes += size
            self.delivery_delays_ms.append(latency_ms)

    def record_parse_result(self, result: ParseResult) -> None:
        self._ensure_started()
        if result.ok:
            self.parse_ok_packets += 1
        else:
            self.parse_error_packets += 1

    def snapshot(self, queue_depth: int = 0) -> MetricsSnapshot:
        elapsed = self._elapsed_s()
        sizes = self.packet_sizes
        delays = self.delivery_delays_ms
        return MetricsSnapshot(
            elapsed_s=elapsed,
            generated_packets=self.generated_packets,
            generated_bytes=self.generated_bytes,
            delivered_packets=self.delivered_packets,
            delivered_bytes=self.delivered_bytes,
            dropped_packets=self.dropped_packets,
            corrupted_packets=self.corrupted_packets,
            parse_ok_packets=self.parse_ok_packets,
            parse_error_packets=self.parse_error_packets,
            queue_depth=queue_depth,
            packets_per_second=self.delivered_packets / elapsed if elapsed else 0.0,
            bytes_per_second=self.delivered_bytes / elapsed if elapsed else 0.0,
            minimum_packet_size=min(sizes) if sizes else 0,
            average_packet_size=sum(sizes) / len(sizes) if sizes else 0.0,
            maximum_packet_size=max(sizes) if sizes else 0,
            average_delivery_delay_ms=(
                sum(delays) / len(delays) if delays else 0.0
            ),
            maximum_delivery_delay_ms=max(delays) if delays else 0.0,
        )

    def export_json(self, path: str | Path, queue_depth: int = 0) -> None:
        Path(path).write_text(
            json.dumps(asdict(self.snapshot(queue_depth)), indent=2) + "\n",
            encoding="utf-8",
        )

    def export_csv(self, path: str | Path, queue_depth: int = 0) -> None:
        values = asdict(self.snapshot(queue_depth))
        with Path(path).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values))
            writer.writeheader()
            writer.writerow(values)

    def _ensure_started(self) -> None:
        if self.started_at is None:
            self.started_at = self._monotonic()

    def _elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        if self.stopped_at is not None:
            end = self.stopped_at
        elif self.paused_at is not None:
            end = self.paused_at
        else:
            end = self._monotonic()
        return max(0.0, end - self.started_at - self.paused_total_s)
