from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum

from common.packet import Packet
from packet.encoder import PacketEncoder
from packet.protocol import FieldSpec, PacketDefinition, ProtocolProfile
from simulator.scenario_config import ScenarioConfig


class ManualPacketSource:
    """Build valid packets from editable engineering-unit field values."""

    def __init__(
        self,
        profile: ProtocolProfile,
        config: ScenarioConfig,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.profile = profile
        self.config = config
        self._monotonic = monotonic
        self._sequence_number = 0
        self._last_emit: dict[str, float] = {}
        self._definitions = {
            definition.name: definition
            for definition in profile.packet_definitions
        }
        self._validate_config()

    @property
    def packet_names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def definition(self, packet_name: str) -> PacketDefinition:
        try:
            return self._definitions[packet_name]
        except KeyError as exc:
            raise ValueError(f"unknown packet name: {packet_name}") from exc

    def field_names(self, packet_name: str) -> tuple[str, ...]:
        return tuple(field.name for field in self.definition(packet_name).fields)

    def get_value(self, packet_name: str, field_name: str) -> object:
        self._field(packet_name, field_name)
        return self.config.packet_values[packet_name][field_name]

    def set_value(
        self,
        packet_name: str,
        field_name: str,
        value: object,
    ) -> object:
        field = self._field(packet_name, field_name)
        converted = self._convert_user_value(field, value)
        # Metadata validation is separate from Protobuf serialization.
        field.validate(converted)
        self.config.packet_values[packet_name][field_name] = converted
        return converted

    def get_period_s(self, packet_name: str) -> float:
        definition = self.definition(packet_name)
        return float(
            self.config.update_periods_s.get(
                packet_name,
                definition.update_period_s,
            )
        )

    def set_period_s(self, packet_name: str, period_s: float) -> None:
        self.definition(packet_name)
        if period_s <= 0.0:
            raise ValueError("update period must be positive")
        self.config.update_periods_s[packet_name] = float(period_s)

    def reset_schedule(self) -> None:
        self._last_emit.clear()

    def due_packet_names(self, now: float | None = None) -> list[str]:
        now = self._monotonic() if now is None else now
        due: list[str] = []
        for packet_name in self.packet_names:
            last_emit = self._last_emit.get(packet_name)
            if last_emit is None:
                due.append(packet_name)
                self._last_emit[packet_name] = now
                continue

            period_s = self.get_period_s(packet_name)
            elapsed_s = now - last_emit
            due_count = int((elapsed_s + 1e-9) / period_s)
            if due_count <= 0:
                continue

            # Catch up missed scheduler intervals while bounding one GUI tick.
            due_count = min(due_count, 1000)
            due.extend([packet_name] * due_count)
            self._last_emit[packet_name] = last_emit + due_count * period_s
        return due

    def encode_once(
        self,
        packet_name: str,
        encoder: PacketEncoder,
        timestamp: datetime | None = None,
    ) -> bytes:
        definition = self.definition(packet_name)
        self._sequence_number = (self._sequence_number + 1) & 0xFFFFFFFF
        packet = Packet(
            protocol_version=self.profile.protocol_version,
            message_type=definition.message_type,
            source_id=definition.source_id,
            destination_id=100,
            packet_id=definition.packet_id,
            sequence_number=self._sequence_number,
            timestamp=timestamp or datetime.now(timezone.utc),
            payload=dict(self.config.packet_values[packet_name]),
        )
        return encoder.encode(packet)

    @staticmethod
    def decode_raw_hex(text: str) -> bytes:
        cleaned = "".join(text.replace("0x", "").replace("0X", "").split())
        if not cleaned:
            raise ValueError("raw packet is empty")
        if len(cleaned) % 2:
            raise ValueError("raw hexadecimal input must contain complete bytes")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError("raw packet contains non-hexadecimal characters") from exc

    def _field(self, packet_name: str, field_name: str) -> FieldSpec:
        for field in self.definition(packet_name).fields:
            if field.name == field_name:
                return field
        raise ValueError(f"unknown field {packet_name}.{field_name}")

    def _validate_config(self) -> None:
        for packet_name, definition in self._definitions.items():
            if packet_name not in self.config.packet_values:
                raise ValueError(f"scenario has no values for {packet_name}")
            values = self.config.packet_values[packet_name]
            expected = {field.name for field in definition.fields}
            missing = expected.difference(values)
            if missing:
                raise ValueError(
                    f"scenario is missing {packet_name} fields: {sorted(missing)}"
                )
            unknown = set(values).difference(expected)
            if unknown:
                raise ValueError(
                    f"scenario contains unknown {packet_name} fields: {sorted(unknown)}"
                )
            for field in definition.fields:
                self.set_value(packet_name, field.name, values[field.name])
            self.set_period_s(packet_name, self.get_period_s(packet_name))

    @staticmethod
    def _convert_user_value(field: FieldSpec, value: object) -> object:
        if isinstance(value, Enum):
            return value
        if value is None:
            return None

        text = str(value).strip()
        if text.lower() in {"none", "null", "-"}:
            return None
        if field.enum_values:
            labels = {label.upper(): label for label in field.enum_values}
            try:
                label = labels[text.upper()]
            except KeyError as exc:
                raise ValueError(
                    f"{field.name} must be one of {sorted(labels.values())}"
                ) from exc
            return field.enum_type(label) if field.enum_type is not None else label
        if field.value_type == "bool":
            if text.lower() in {"1", "true", "yes", "on"}:
                return True
            if text.lower() in {"0", "false", "no", "off"}:
                return False
            raise ValueError(f"{field.name} must be true or false")
        if field.value_type == "int":
            return int(text, 0)
        if field.value_type == "float":
            return float(text)
        raise ValueError(f"unsupported value type for {field.name}: {field.value_type}")
