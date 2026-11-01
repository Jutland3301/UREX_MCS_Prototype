from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
import pytest
from integration.backend import MockBackend, Reception
from integration.codec import PacketFactory, encode, decode
from integration.engine import EventLog, PiEngine
from integration.transport import ZmqTransport
from packet.generated import integration_pb2 as pb


def test_event_settings_override_later_status_and_roundtrip(tmp_path):
    config=pb.ModemConfiguration(frequency_hz=2400000000,spreading_factor=7,
                                  bandwidth_hz=125000,modulation='LoRa',radio_id='radio-A')
    reception=Reception(b'\x00\xff',1234,modem_config=config)
    # The hardware changes settings after queueing this RX event.
    config.frequency_hz=2450000000
    assert reception.modem_config.frequency_hz==2400000000
    factory=PacketFactory()
    log=EventLog(tmp_path)
    status=MockBackend().snapshot()
    status.components[1].configuration_summary='later setting 2450000000 Hz SF12'
    log.record('status',packet=factory.make('status',status))
    packet=factory.make('radio_receive',pb.RadioReceive(payload=reception.payload,
        modem_config=reception.modem_config),timestamp_ms=reception.timestamp_ms)
    decoded=decode(encode(packet))
    row=log.record('radio_receive',direction='RX',packet=decoded)
    assert row['modem_config_source']=='rx_event'
    assert row['modem_frequency_hz']==2400000000
    assert row['modem_spreading_factor']==7
    assert row['config_status_time_unix_ms']==''
    legacy=log.record('radio_receive',packet=factory.make('radio_receive',pb.RadioReceive(payload=b'old')))
    assert legacy['modem_config_source']=='last_status_summary'
    assert legacy['modem_frequency_hz']==''  # Never parse/guess event settings from a Status string.
    log.close()
    with sqlite3.connect(next(tmp_path.glob('*.db'))) as db:
        stored=db.execute("SELECT modem_frequency_hz,modem_spreading_factor,modem_radio_id FROM events WHERE modem_config_source='rx_event'").fetchone()
        assert stored==(2400000000,7,'radio-A')
    json_rows=[json.loads(x) for x in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
    assert json_rows[1]['modem_frequency_hz']==2400000000


def test_config_absent_partial_and_invalid():
    log=EventLog()
    f=PacketFactory()
    absent=log.record('radio_receive',packet=f.make('radio_receive',pb.RadioReceive(payload=b'x')))
    assert absent['modem_config_source']=='unavailable'
    partial=f.make('radio_receive',pb.RadioReceive(payload=b'x',modem_config=pb.ModemConfiguration(modulation='FLRC')))
    row=log.record('radio_receive',packet=partial)
    assert row['modem_config_source']=='rx_event' and row['modem_modulation']=='FLRC'
    assert row['modem_spreading_factor']==''
    with pytest.raises(ValueError,match='positive'):
        f.make('radio_receive',pb.RadioReceive(payload=b'x',modem_config=pb.ModemConfiguration(frequency_hz=0)))
    with pytest.raises(ValueError,match='positive'):
        f.make('radio_receive',pb.RadioReceive(payload=b'x',modem_config=pb.ModemConfiguration(frequency_hz=2**64-1)))
    empty=log.record('radio_receive',packet=f.make('radio_receive',pb.RadioReceive(
        payload=b'x',modem_config=pb.ModemConfiguration())))
    assert empty['modem_config_source']=='rx_event_empty'


def spin(app,predicate,timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        time.sleep(.002)
    raise AssertionError('Timed out processing Qt events')


def test_network_and_sqlite_owner_and_gui_progress_during_slow_write(tmp_path,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from gui.integration_window import IntegrationWindow
    app=QApplication.instance() or QApplication([])
    main_id=threading.get_ident()
    records=[];closed=[];entered=threading.Event()
    original_record=EventLog.record
    original_close=EventLog.close
    def slow_record(self,*a,**kw):
        if a and a[0]=='radio_receive' and kw.get('direction')=='RX':
            records.append(threading.get_ident())
            entered.set()
            time.sleep(.25)
        return original_record(self,*a,**kw)
    def close(self):
        if self._db is not None:closed.append(threading.get_ident())
        return original_close(self)
    monkeypatch.setattr(EventLog,'record',slow_record)
    monkeypatch.setattr(EventLog,'close',close)
    window=IntegrationWindow('tcp://*:0',str(tmp_path/'mcs'))
    pi_wire=ZmqTransport(window.transport.bound_endpoint.replace('0.0.0.0','127.0.0.1'),pi=True)
    pi=PiEngine(pi_wire,MockBackend(delay_s=0))
    pi_wire.start()
    timer=QTimer();timer.timeout.connect(pi.tick);timer.start(5)
    heartbeat=[]
    gui_timer=QTimer();gui_timer.timeout.connect(lambda:heartbeat.append(time.monotonic()));gui_timer.start(5)
    worker_thread=window.controller.thread
    try:
        spin(app,lambda:window.controller.fresh)
        start=time.perf_counter()
        cmd=window.controller.transmit(b'worker-test')
        assert time.perf_counter()-start<.1
        spin(app,entered.is_set)
        count=len(heartbeat)
        until=time.monotonic()+.1
        spin(app,lambda:time.monotonic()>=until)
        assert len(heartbeat)-count>=5  # GUI continues while SQLite/log worker is delayed.
        spin(app,lambda:window.rx_table.rowCount()>0)
        assert window.controller.commands[cmd].state=='TX_COMPLETED'
        assert records and all(t!=main_id for t in records)
        assert window.controller.worker_thread_id==records[0]
        assert window.rx_table.item(0,6).text()=='rx_event'
    finally:
        gui_timer.stop();timer.stop();pi.close();window.close()
    assert not worker_thread.isRunning()
    assert closed==[records[0]]  # SQLite closes on its creating worker thread.
    with sqlite3.connect(next((tmp_path/'mcs').glob('*.db'))) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE kind='radio_receive'").fetchone()[0]==1


def test_close_drains_queued_request_and_final_log_events(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from gui.integration_window import IntegrationWindow
    app=QApplication.instance() or QApplication([])
    window=IntegrationWindow('tcp://*:0',str(tmp_path))
    pi_wire=ZmqTransport(window.transport.bound_endpoint.replace('0.0.0.0','127.0.0.1'),pi=True)
    pi=PiEngine(pi_wire,MockBackend())
    pi_wire.start()
    timer=QTimer();timer.timeout.connect(pi.tick);timer.start(5)
    events=[]
    window.controller.event_recorded.connect(events.append)
    try:
        spin(app,lambda:window.controller.fresh)
        cmd=window.controller.transmit(b'close-test')
        window.close()  # Queued transmit is processed before queued shutdown.
        assert any(e['row']['command_id']==cmd and e['row']['kind']=='transmit_request' for e in events)
    finally:
        timer.stop();pi.close();window.close()
    with sqlite3.connect(next(tmp_path.glob('*.db'))) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE command_id=? AND kind='transmit_request'",(cmd,)).fetchone()[0]==1
