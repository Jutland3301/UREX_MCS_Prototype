from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import MessageType


@dataclass
class Packet:
    """
    Logical packet representation.

    This is deliberately transport-neutral. Binary layout/JSON encoding,
    byte order, field widths, and final packet IDs remain TBD until the
    team agrees on the protocol.
    """

    protocol_version: int = 1
    message_type: MessageType = MessageType.TELEMETRY
    source_id: int = 0
    destination_id: int = 0
    packet_id: int = 0
    sequence_number: int = 0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: dict[str, Any] = field(default_factory=dict)
    crc: int | None = None

    @property
    def payload_length(self) -> int:
        # Placeholder logical length.
        # Replace when the serialization format is finalized.
        return len(repr(self.payload).encode("utf-8"))
