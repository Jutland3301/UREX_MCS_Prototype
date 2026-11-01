"""Instrument the existing network GUI; never call Qt widgets from the runner thread."""
from __future__ import annotations
import time
import json
from concurrent.futures import Future
from PySide6.QtCore import QObject, Signal, Slot
from gui.integration_window import IntegrationWindow
from evidence_suite.common import stats


class Bridge(QObject):
    requested = Signal(object)
    def __init__(self):
        super().__init__()
        self.requested.connect(self.execute)
    @Slot(object)
    def execute(self, item):
        fn, future = item
        try:
            future.set_result(fn())
        except Exception as exc:
            future.set_exception(exc)
    def call(self, fn):
        future = Future()
        self.requested.emit((fn, future))
        return future.result(timeout=15)


class MeasuredWindow(IntegrationWindow):
    def __init__(self, endpoint, log_dir, stream):
        self.stream = stream
        self.phase = 'STARTUP'
        self.previous_tick = None
        self.tick_gaps = []
        self.tick_costs = []
        self.log_costs = []
        self.rx = []
        self.events = []
        super().__init__(endpoint, log_dir)
        original = self.controller.log.record
        def record(*args, **kwargs):
            start = time.perf_counter_ns()
            row = original(*args, **kwargs)
            cost = (time.perf_counter_ns()-start)/1e6
            self.log_costs.append(cost)
            # Original EventLog row is retained in DB + JSONL; sidecar provides phase association.
            event = dict(phase=self.phase, kind=row['kind'], direction=row['direction'],
                         session_id=row['session_id'], sequence=row['sequence'],
                         command_id=row['command_id'], state=row['state'], payload_hex=row['payload_hex'],
                         local_unix_ms=row['local_time_unix_ms'], log_cost_ms=cost,
                         monotonic_ns=time.perf_counter_ns())
            self.events.append(event)
            if row['kind'] == 'radio_receive':
                self.rx.append(event)
            self.stream.write(json.dumps(event)+'\n')
            self.stream.flush()
            return row
        self.controller.log.record = record
    def tick(self):
        start = time.perf_counter_ns()
        if self.previous_tick is not None:
            gap = (start-self.previous_tick)/1e6
            self.tick_gaps.append(max(0, gap-20))
            self.stream.write(json.dumps(dict(
                metric='gui_timer', phase=self.phase, monotonic_ns=start,
                interval_ms=gap, lateness_ms=max(0,gap-20)))+'\n')
        self.previous_tick = start
        try:
            super().tick()
        except Exception as exc:
            self.probe_error=f'{type(exc).__name__}: {exc}'
            if hasattr(self,'timer'):
                self.timer.stop()
        finally:
            self.tick_costs.append((time.perf_counter_ns()-start)/1e6)
    def begin_phase(self, name):
        self.phase = name
        self.controller.log.run_id = name
        self.tick_gaps.clear()
        self.tick_costs.clear()
        self.log_costs.clear()
        return len(self.events)
    def phase_stats(self, start):
        rows = self.events[start:]
        rx = [r for r in rows if r['kind']=='radio_receive']
        valid = [r for r in rows if r['direction']=='RX']
        keys = [(r['session_id'],r['sequence']) for r in valid]
        return dict(events=len(rows), radio_receive=len(rx), valid_receive=len(valid),
                    duplicate_valid_records=len(keys)-len(set(keys)),
                    gui_lateness_ms=stats(self.tick_gaps), gui_tick_cost_ms=stats(self.tick_costs),
                    log_cost_ms=stats(self.log_costs),
                    sequence_gap_events=sum(r['kind']=='SEQUENCE_GAP' for r in rows))
