from __future__ import annotations

import csv
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from packet.parser import ParseResult

EQUIPMENT_FAULT_NAMES = (
    "SIM_INJECT_HIGH_TEMPERATURE",
    "SIM_INJECT_LOW_VOLTAGE",
    "SIM_INJECT_CAN_ERROR",
    "SIM_INJECT_CAN_BUS_OFF",
    "SIM_INJECT_WEAK_RADIO",
    "SIM_INJECT_SDR_OVERRUN",
)
FAULT_NAMES = (
    "SIM_INJECT_CRC_ERROR",
    "SIM_INJECT_PACKET_DROP",
    "SIM_INJECT_LINK_LOSS",
    *EQUIPMENT_FAULT_NAMES,
)


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
    equipment_fault_packet_total: int = 0
    fault_injections: dict[str, int] = field(default_factory=dict)
    equipment_fault_packets: dict[str, int] = field(default_factory=dict)


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
        self.fault_injections = {name: 0 for name in FAULT_NAMES}
        self.equipment_fault_packet_total = 0
        self.equipment_fault_packets = {
            name: 0 for name in EQUIPMENT_FAULT_NAMES
        }

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

    def record_fault_injection(self, fault_name: str) -> None:
        """Count a requested fault; this does not start the timing clock."""
        if fault_name not in self.fault_injections:
            raise ValueError(f"unknown fault: {fault_name}")
        self.fault_injections[fault_name] += 1

    def record_equipment_fault_packet(self, fault_names: Iterable[str]) -> None:
        """Count one generated packet and each active equipment fault type."""
        names = set(fault_names)
        for name in names:
            if name not in self.equipment_fault_packets:
                raise ValueError(f"not an equipment fault: {name}")
        if names:
            self.equipment_fault_packet_total += 1
        for name in names:
            self.equipment_fault_packets[name] += 1

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
            equipment_fault_packet_total=self.equipment_fault_packet_total,
            fault_injections=dict(self.fault_injections),
            equipment_fault_packets=dict(self.equipment_fault_packets),
        )

    def export_json(self, path: str | Path, queue_depth: int = 0) -> None:
        Path(path).write_text(
            json.dumps(asdict(self.snapshot(queue_depth)), indent=2) + "\n",
            encoding="utf-8",
        )

    def export_csv(self, path: str | Path, queue_depth: int = 0) -> None:
        values = asdict(self.snapshot(queue_depth))
        for group in ("fault_injections", "equipment_fault_packets"):
            for name, count in values.pop(group).items():
                values[f"{group}_{name.lower()}"] = count
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
