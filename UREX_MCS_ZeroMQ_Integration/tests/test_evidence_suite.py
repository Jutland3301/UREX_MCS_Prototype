from __future__ import annotations
import argparse
import json
import sqlite3
import zipfile
from pathlib import Path
import pytest
from evidence_suite.common import percentile, validate_plan
from evidence_suite.run import reconcile
from integration.backend import MockBackend
from integration.codec import PacketFactory
from integration.engine import EventLog
from packet.generated import integration_pb2 as pb


def plan():
    return dict(pi_url='http://192.168.1.20:8765',token='test-token',mcs_host='192.168.1.10',
                h1=dict(phases=[dict(name='concurrent',duration_s=1,command_hz=1)]),
                h3=dict(steps=[dict(payload_hex='000aff',expected_rx_hex='000aff')]))


def test_plan_does_not_supply_invented_radio_commands():
    example=json.loads((Path(__file__).parents[1]/'evidence-plan.example.json').read_text())
    assert example['h3']['steps']==[]
    with pytest.raises(ValueError):validate_plan(example)
    assert validate_plan(plan())['h3']['steps'][0]['payload_hex']=='000aff'


@pytest.mark.parametrize('change',[
    {'h1':{'phases':[{'duration_s':-1,'command_hz':1}]}},
    {'h2':{'payload_bytes':2}},
    {'h3':{'steps':[{'payload_hex':'xx'}]}},
    {'h3':{'repeats':0}},
])
def test_invalid_plan(change):
    p=plan();p.update(change)
    with pytest.raises(ValueError):validate_plan(p)


def test_percentile_empty_and_interpolated():
    assert percentile([], .95) is None
    assert percentile([1,3], .5)==2


def test_db_fields_binary_null_zero_and_modem_config(tmp_path):
    log=EventLog(tmp_path)
    factory=PacketFactory()
    status=MockBackend().snapshot()
    status.components[1].configuration_summary='freq_hz=2400000000; sf=7'
    log.record('status',packet=factory.make('status',status))
    log.run_id='H1-1'
    row=log.record('radio_receive',direction='RX',packet=factory.make('radio_receive',pb.RadioReceive(payload=b'\x00\xff',rssi_dbm=0)))
    assert row['modem_config_summary']=='freq_hz=2400000000; sf=7'
    old=factory.make('radio_receive',pb.RadioReceive(payload=b'x'))
    other=PacketFactory()
    log.record('status',packet=other.make('status',MockBackend().snapshot()))
    assert log.record('radio_receive',packet=old)['modem_config_summary']==''
    for i in range(1001):log.record('NOTE',detail=i)
    log.close();log.close()
    with sqlite3.connect(next(tmp_path.glob('*.db'))) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1005
        assert db.execute("SELECT run_id,payload_hex,rssi_dbm,snr_db FROM events WHERE direction='RX'").fetchone()==('H1-1','00ff',0,None)
    assert len(log.rows)==1000
    assert not list(tmp_path.glob('*.csv'))


def test_reconcile_counts_gaps_and_duplicates(tmp_path):
    dbfile=tmp_path/'data.db'
    with sqlite3.connect(dbfile) as db:
        db.execute('CREATE TABLE events(session_id TEXT,sequence INTEGER,kind TEXT,direction TEXT)')
        db.executemany('INSERT INTO events VALUES(?,?,?,?)',[('session',1,'radio_receive','RX')]*2)
    archive=tmp_path/'pi.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('pi-traffic.jsonl','\n'.join(json.dumps(dict(session_id='session',sequence=n,
                   kind='radio_receive',direction='TO_MCS',forwarded=True)) for n in [1,2]))
    result=reconcile(archive,dbfile)
    assert result['status']=='MISMATCH'
    assert result['missing_from_db']==[['session',2]]
    assert result['duplicate_db_records']==1
