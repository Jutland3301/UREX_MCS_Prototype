from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable


MessageHandler = Callable[[bytes], None]
StatusHandler = Callable[["TransportStatus"], None]


class TransportStatus(str, Enum):
    STOPPED = "STOPPED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


class BaseTransport(ABC):
    """Transport boundary used by simulator, ZeroMQ, or MQTT adapters."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = TransportStatus.STOPPED
        self._message_handler: MessageHandler | None = None
        self._status_handler: StatusHandler | None = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    def set_status_handler(self, handler: StatusHandler) -> None:
        self._status_handler = handler

    def _emit_message(self, message: bytes) -> None:
        if self._message_handler is not None:
            self._message_handler(message)

    def _set_status(self, status: TransportStatus) -> None:
        self.status = status
        if self._status_handler is not None:
            self._status_handler(status)

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send(self, message: bytes) -> None:
        raise NotImplementedError
