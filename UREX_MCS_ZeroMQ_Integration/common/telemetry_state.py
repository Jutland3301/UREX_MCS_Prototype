from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from common.enums import LinkStatus
from common.telemetry import TelemetryFrame
from packet.parser import ParseResult
from packet.protocol import ProtocolProfile


class TelemetryState:
    """Merge independently received packet updates into one GUI snapshot."""

    def __init__(
        self,
        profile: ProtocolProfile,
        heartbeat_timeout_s: float = 3.0,
    ) -> None:
        self.profile = profile
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.frame = TelemetryFrame()
        self.last_receive_time: datetime | None = None
        self.last_update_by_packet_id: dict[int, datetime] = {}

    def apply(self, result: ParseResult) -> TelemetryFrame:
        if not result.ok or result.packet is None:
            raise ValueError("only a successful ParseResult can update telemetry")

        packet = result.packet
        definition = self.profile.packet_definition(packet.meta.packet_id)
        target = getattr(self.frame, definition.target)

        if definition.target == "spacecraft":
            target.parameters.update(packet.fields)
        else:
            for field_name, value in packet.fields.items():
                if not hasattr(target, field_name):
                    raise AttributeError(
                        f"{definition.target} has no telemetry field {field_name!r}"
                    )
                setattr(target, field_name, value)

        now = datetime.now(timezone.utc)
        was_connected = self.frame.link.status == LinkStatus.CONNECTED
        self.frame.meta = deepcopy(packet.meta)
        self.frame.raw_packet = result.raw_packet
        self.frame.link.status = LinkStatus.CONNECTED
        self.frame.link.heartbeat_ok = True
        self.frame.link.heartbeat_age_ms = 0
        self.frame.link.last_rx_timestamp = now
        self.frame.link.rx_message_count += 1
        if not was_connected and self.last_receive_time is not None:
            self.frame.link.reconnect_count += 1
        self.last_receive_time = now
        self.last_update_by_packet_id[packet.meta.packet_id] = now
        return self.snapshot()

    def record_parse_failure(self) -> TelemetryFrame:
        self.frame.link.rx_error_count += 1
        return self.snapshot()

    def set_transport_connected(self, connected: bool) -> TelemetryFrame:
        was_connected = self.frame.link.status == LinkStatus.CONNECTED
        self.frame.link.status = (
            LinkStatus.CONNECTED if connected else LinkStatus.DISCONNECTED
        )
        self.frame.link.heartbeat_ok = connected
        if connected and not was_connected:
            self.frame.link.reconnect_count += 1
        return self.snapshot()

    def refresh_staleness(
        self,
        now: datetime | None = None,
    ) -> TelemetryFrame:
        now = now or datetime.now(timezone.utc)
        if self.last_receive_time is None:
            return self.snapshot()

        age_ms = int((now - self.last_receive_time).total_seconds() * 1000)
        self.frame.link.heartbeat_age_ms = max(0, age_ms)
        if age_ms > int(self.heartbeat_timeout_s * 1000):
            self.frame.link.status = LinkStatus.DISCONNECTED
            self.frame.link.heartbeat_ok = False
        return self.snapshot()

    def is_packet_stale(
        self,
        packet_id: int,
        now: datetime | None = None,
    ) -> bool:
        definition = self.profile.packet_definition(packet_id)
        last_update = self.last_update_by_packet_id.get(packet_id)
        if last_update is None:
            return True
        now = now or datetime.now(timezone.utc)
        allowed_age = max(
            self.heartbeat_timeout_s,
            definition.update_period_s * 3.0,
        )
        return (now - last_update).total_seconds() > allowed_age

    def snapshot(self) -> TelemetryFrame:
        return deepcopy(self.frame)
