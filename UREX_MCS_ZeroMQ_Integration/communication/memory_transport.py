from __future__ import annotations

from communication.base_transport import BaseTransport, TransportStatus


class MemoryTransport(BaseTransport):
    """In-process adapter that exercises the same byte boundary as real I/O."""

    def __init__(self) -> None:
        super().__init__("SIMULATOR-BINARY")
        self.sent_messages: list[bytes] = []

    def start(self) -> None:
        self._set_status(TransportStatus.CONNECTED)

    def stop(self) -> None:
        self._set_status(TransportStatus.STOPPED)

    def send(self, message: bytes) -> None:
        if self.status != TransportStatus.CONNECTED:
            raise RuntimeError("transport is not connected")
        self.sent_messages.append(bytes(message))

    def feed_incoming(self, message: bytes) -> None:
        if self.status != TransportStatus.CONNECTED:
            raise RuntimeError("transport is not connected")
        self._emit_message(bytes(message))
