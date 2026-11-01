"""Own ZeroMQ, controller and SQLite in one QThread; GUI sees detached snapshots."""
from __future__ import annotations

import time
import threading
from collections import OrderedDict
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from PySide6.QtCore import (QObject, QThread, QTimer, Signal, Slot, QEventLoop,
                            QCoreApplication, QEvent)

from integration.engine import McsController, TrackedCommand
from integration.transport import ZmqTransport
from packet.generated import integration_pb2 as pb


class IoWorker(QObject):
    ready = Signal(str)
    snapshot = Signal(object)
    failed = Signal(str)

    def __init__(self, endpoint, log_dir):
        super().__init__()
        self.endpoint, self.log_dir = endpoint, log_dir
        self.controller = None
        self.timer = None
        self.pending_events = []
        self.last_publish = 0.0
        self.error = None
        self.flush_marker = 0

    @Slot()
    def start(self):
        try:
            transport = ZmqTransport(self.endpoint)
            # SQLite connection and ZeroMQ socket are both created in this worker.
            self.controller = McsController(transport, log_dir=self.log_dir)
            original = self.controller.log.record
            def record(*args, **kwargs):
                start = time.perf_counter_ns()
                row = original(*args, **kwargs)
                self.pending_events.append(dict(row=dict(row),
                    log_cost_ms=(time.perf_counter_ns()-start)/1e6,
                    monotonic_ns=time.perf_counter_ns(), worker_thread_id=threading.get_ident()))
                return row
            self.controller.log.record = record
            transport.start()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(10)
            self.publish()
            self.ready.emit(transport.bound_endpoint)
        except Exception as exc:
            self.fatal(exc)

    def publish(self):
        if self.controller is None:
            return
        c = self.controller
        events, self.pending_events = self.pending_events, []
        self.snapshot.emit(dict(
            status=c.status.SerializeToString() if c.status is not None else None,
            last_status=c.last_status,
            commands=OrderedDict((key, replace(value)) for key,value in c.commands.items()),
            events=events, error=self.error,
            flush_marker=self.flush_marker,
            worker_thread_id=threading.get_ident()))
        self.last_publish = time.monotonic()

    @Slot()
    def tick(self):
        try:
            self.controller.tick()
            # Batch snapshots; file/network I/O never runs on the GUI thread.
            if time.monotonic()-self.last_publish >= .1:
                self.publish()
        except Exception as exc:
            self.fatal(exc)

    @Slot(object)
    def request(self, item):
        action, value = item
        if self.controller is None or self.error:
            return
        if action == 'phase':
            # Publish preceding events with their original phase before switching.
            self.publish()
            self.controller.log.run_id = value
        elif action == 'flush':
            self.flush_marker = value
            self.publish()
        elif action == 'transmit':
            command_id, payload = value
            try:
                self.controller.transmit(payload, command_id=command_id)
            except Exception as exc:
                self.controller.commands[command_id] = TrackedCommand(
                    command_id, payload, 'REJECTED', 0, 'LOCAL_SEND_FAILED', str(exc))
                try:
                    self.controller.log.record('LOCAL_SEND_FAILED',
                        detail=dict(command_id=command_id, reason=str(exc)))
                except Exception as log_exc:
                    self.fatal(log_exc)
            self.publish()

    def fatal(self, exc):
        self.error = f'{type(exc).__name__}: {exc}'
        self.failed.emit(self.error)
        self.stop()

    @Slot()
    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        try:
            if self.controller is not None:
                # Closing SQLite happens on the same thread that opened it.
                self.controller.close()
                self.publish()
        except Exception as exc:
            self.failed.emit(f'Shutdown error: {exc}')
        finally:
            self.controller = None
            QThread.currentThread().quit()


class ViewLog:
    """GUI history only: no SQLite connection, file handle or network socket."""
    def __init__(self, owner):
        self.rows = []
        self.owner = owner
        self._run_id = ''

    @property
    def run_id(self):
        return self._run_id

    @run_id.setter
    def run_id(self, value):
        self._run_id = value
        self.owner.requested.emit(('phase', value))


class ControllerView(QObject):
    requested = Signal(object)
    stopping = Signal()
    event_recorded = Signal(object)
    """Nonblocking GUI command queue and detached worker snapshots."""

    def __init__(self, endpoint, log_dir, parent=None):
        super().__init__(parent)
        self.status = None
        self.last_status = None
        self.commands = OrderedDict()
        self.receptions = []
        self.log = ViewLog(self)
        self.transport = SimpleNamespace(bound_endpoint=endpoint)
        self.error = None
        self.worker_thread_id = None
        self.last_flush = 0
        self._next_flush = 0
        self._closed = False
        self._pending_ids = set()
        self.thread = QThread(self)
        self.worker = IoWorker(endpoint, log_dir)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.snapshot.connect(self.accept_snapshot)
        self.worker.failed.connect(self.accept_error)
        self.requested.connect(self.worker.request)
        self.stopping.connect(self.worker.stop)
        self.thread.finished.connect(self.worker.deleteLater)
        # Only startup waits (with event processing); live transmit/tick do not wait.
        loop = QEventLoop()
        ready = []
        def started(bound):
            self.transport.bound_endpoint = bound
            ready.append(True)
            loop.quit()
        self.worker.ready.connect(started)
        self.worker.failed.connect(loop.quit)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(5000)
        self.thread.start()
        loop.exec()
        timeout.stop()
        self.worker.ready.disconnect(started)
        self.worker.failed.disconnect(loop.quit)
        if not ready or self.error:
            self.close()
            raise RuntimeError(self.error or 'MCS worker startup timeout')

    @Slot(str)
    def accept_error(self, error):
        self.error = error
        self.last_status = None

    @Slot(object)
    def accept_snapshot(self, data):
        self.worker_thread_id = data['worker_thread_id']
        self.last_flush = max(self.last_flush, data['flush_marker'])
        self.status = (pb.Status.FromString(data['status']) if data['status'] is not None else None)
        self.last_status = data['last_status'] if not data['error'] else None
        if data['error']:
            self.error = data['error']
        commands = data['commands']
        self._pending_ids.difference_update(commands)
        # Preserve newly queued GUI commands until the worker has processed them.
        for key in self._pending_ids:
            if key in self.commands:
                commands[key] = self.commands[key]
        self.commands = commands
        for event in data['events']:
            row = event['row']
            self.log.rows.append(row)
            del self.log.rows[:-1000]
            if row['kind'] == 'radio_receive':
                self.receptions.append(row)
                del self.receptions[:-1000]
            self.event_recorded.emit(event)

    @property
    def fresh(self):
        return (not self.error and not self._closed and self.last_status is not None
                and time.monotonic()-self.last_status < 3.0)

    def transmit(self, payload):
        if not self.fresh:
            raise ValueError('No current Pi Status; transmitting is disabled')
        if not payload or len(payload)>self.status.max_tx_payload_bytes:
            raise ValueError(f'Payload must be 1–{self.status.max_tx_payload_bytes} bytes')
        if not any(c.component == pb.RADIO and c.health == pb.READY for c in self.status.components):
            raise ValueError('Pi radio is not READY')
        if sum(c.state in ('QUEUED','SENT','ACCEPTED') for c in self.commands.values()) >= 1024:
            raise ValueError('Too many pending commands')
        command_id = str(uuid4())
        self.commands[command_id] = TrackedCommand(command_id, bytes(payload), 'QUEUED', 0)
        self._pending_ids.add(command_id)
        self.requested.emit(('transmit',(command_id,bytes(payload))))
        return command_id

    def tick(self):
        if self.error:
            raise RuntimeError(self.error)

    def flush(self):
        self._next_flush += 1
        self.requested.emit(('flush', self._next_flush))
        return self._next_flush

    def close(self):
        if self._closed:
            return
        if self.thread.isRunning():
            self.stopping.emit()
            if not self.thread.wait(10000):
                raise RuntimeError('MCS worker did not finish shutdown within 10 seconds')
        # Deliver final committed records before instrumentation files are closed.
        QCoreApplication.sendPostedEvents(self, QEvent.Type.MetaCall)
        self._closed = True
