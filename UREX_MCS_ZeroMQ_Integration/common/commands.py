from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import CommandStatus


@dataclass
class Command:
    command_id: int
    command_name: str
    source_id: int = 0
    destination_id: int = 0
    sequence_number: int = 0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    parameters: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 5.0
    acknowledgement_required: bool = True
    status: CommandStatus = CommandStatus.CREATED


@dataclass
class CommandResponse:
    command_id: int
    command_sequence: int
    source_id: int
    status: CommandStatus
    response_timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    result_code: str | None = None
    message: str | None = None
