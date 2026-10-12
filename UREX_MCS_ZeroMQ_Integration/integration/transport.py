"""One-owner ZeroMQ I/O. Call start/poll/send/stop from the same thread."""
from __future__ import annotations

import threading

import zmq

from communication.base_transport import BaseTransport, TransportStatus
from integration.codec import MAX_BODY

PI_IDENTITY = b"urex-pi"


class ZmqTransport(BaseTransport):
    def __init__(self, endpoint: str, *, pi: bool = False) -> None:
        super().__init__("ZeroMQ")
        self.endpoint, self.pi = endpoint, pi
        self._socket = None
        self._context = None
        self._owner = None
        self._peer = False
        self.bound_endpoint = endpoint

    def _check_owner(self) -> None:
        if self._owner != threading.get_ident():
            raise RuntimeError("ZeroMQ socket must be used by its creating thread")

    def start(self) -> None:
        if self._socket is not None:
            self._check_owner()
            return
        self._owner = threading.get_ident()
        self._context = zmq.Context()
        socket = self._context.socket(zmq.DEALER if self.pi else zmq.ROUTER)
        self._socket = socket
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SNDHWM, 1000)
        socket.setsockopt(zmq.RCVHWM, 1000)
        socket.setsockopt(zmq.MAXMSGSIZE, MAX_BODY + 9)
        socket.setsockopt(zmq.HEARTBEAT_IVL, 1000)
        socket.setsockopt(zmq.HEARTBEAT_TIMEOUT, 3000)
        try:
            if self.pi:
                socket.setsockopt(zmq.IDENTITY, PI_IDENTITY)
                socket.setsockopt(zmq.IMMEDIATE, 1)
                socket.setsockopt(zmq.RECONNECT_IVL, 250)
                socket.setsockopt(zmq.RECONNECT_IVL_MAX, 2000)
                socket.connect(self.endpoint)
            else:
                socket.setsockopt(zmq.ROUTER_MANDATORY, 1)
                socket.setsockopt(zmq.ROUTER_HANDOVER, 1)
                socket.bind(self.endpoint)
                self.bound_endpoint = socket.getsockopt_string(zmq.LAST_ENDPOINT)
        except Exception:
            self.stop()
            raise
        self._set_status(TransportStatus.CONNECTING)

    def poll(self, budget: int = 100) -> None:
        self._check_owner()
        if self._socket is None:
            return
        for _ in range(budget):
            try:
                parts = self._socket.recv_multipart(zmq.DONTWAIT)
            except zmq.Again:
                break
            if self.pi:
                if len(parts) != 1:
                    continue
                frame = parts[0]
            else:
                if len(parts) != 2 or parts[0] != PI_IDENTITY:
                    continue
                self._peer = True
                frame = parts[1]
            self._emit_message(frame)

    def send(self, message: bytes) -> None:
        self._check_owner()
        if self._socket is None or (not self.pi and not self._peer):
            raise ConnectionError("Pi is not connected")
        try:
            if self.pi:
                self._socket.send(message, zmq.DONTWAIT)
            else:
                self._socket.send_multipart([PI_IDENTITY, message], zmq.DONTWAIT)
        except zmq.ZMQError as exc:
            raise ConnectionError("peer unavailable or outbound queue full") from exc

    def mark_connected(self, connected: bool) -> None:
        self._check_owner()
        self._set_status(TransportStatus.CONNECTED if connected else TransportStatus.DISCONNECTED)

    def stop(self) -> None:
        if self._socket is not None:
            self._check_owner()
            self._socket.close()
            self._socket = None
        if self._context is not None:
            self._context.term()
            self._context = None
        self._peer = False
        self._set_status(TransportStatus.STOPPED)
