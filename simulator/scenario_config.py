from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


@dataclass
class NetworkConditions:
    """User-controlled impairments applied before bytes reach the parser."""

    drop_rate_percent: float = 0.0
    corruption_rate_percent: float = 0.0
    delay_ms: float = 0.0
    jitter_ms: float = 0.0

    def validate(self) -> None:
        for name in ("drop_rate_percent", "corruption_rate_percent"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.delay_ms < 0.0:
            raise ValueError("delay_ms must not be negative")
        if self.jitter_ms < 0.0:
            raise ValueError("jitter_ms must not be negative")


@dataclass
class ExperimentSettings:
    duration_s: float = 60.0
    scheduler_interval_ms: int = 20
    burst_size: int = 1

    def validate(self) -> None:
        if self.duration_s <= 0.0:
            raise ValueError("duration_s must be positive")
        if not 5 <= self.scheduler_interval_ms <= 10_000:
            raise ValueError("scheduler_interval_ms must be between 5 and 10000")
        if not 1 <= self.burst_size <= 10_000:
            raise ValueError("burst_size must be between 1 and 10000")


@dataclass
class ScenarioConfig:
    """Serializable assumptions for a repeatable simulator experiment."""

    name: str = "UREX provisional manual scenario"
    random_seed: int = 3301
    packet_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    update_periods_s: dict[str, float] = field(default_factory=dict)
    network: NetworkConditions = field(default_factory=NetworkConditions)
    experiment: ExperimentSettings = field(default_factory=ExperimentSettings)

    def validate(self) -> None:
        self.network.validate()
        self.experiment.validate()
        for packet_name, period_s in self.update_periods_s.items():
            if float(period_s) <= 0.0:
                raise ValueError(
                    f"update period for {packet_name} must be positive"
                )

    @classmethod
    def load(cls, path: str | Path) -> ScenarioConfig:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        config = cls(
            name=str(data.get("name", "UREX provisional manual scenario")),
            random_seed=int(data.get("random_seed", 3301)),
            packet_values={
                str(packet): dict(values)
                for packet, values in data.get("packet_values", {}).items()
            },
            update_periods_s={
                str(packet): float(period)
                for packet, period in data.get("update_periods_s", {}).items()
            },
            network=NetworkConditions(**data.get("network", {})),
            experiment=ExperimentSettings(**data.get("experiment", {})),
        )
        config.validate()
        return config

    def save(self, path: str | Path) -> None:
        self.validate()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(
                asdict(self),
                indent=2,
                sort_keys=True,
                default=lambda value: (
                    value.value if isinstance(value, Enum) else str(value)
                ),
            )
            + "\n",
            encoding="utf-8",
        )
