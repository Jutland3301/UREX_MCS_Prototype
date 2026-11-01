"""PC entry point: run H1/H3 through the real MCS GUI, H2 on dedicated middleware."""
from __future__ import annotations
import argparse
import csv
import json
import os
import sqlite3
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import Future
import zipfile
from pathlib import Path
from evidence_suite.common import dump, environment, hashes, validate_plan, ResourceSampler


class Remote:
    def __init__(self, plan):
        self.url, self.token = plan['pi_url'].rstrip('/'), plan['token']
    def call(self, operation, body=None, binary=False):
        request = urllib.request.Request(self.url+'/'+operation, json.dumps(body or {}).encode(),
            {'Authorization': 'Bearer '+self.token, 'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=35) as response:
            data = response.read()
        return data if binary else json.loads(data)


def reconcile(pi_zip, db_path):
    """Compare actual proxy-forwarded packet IDs against persisted MCS RX packet IDs."""
    with zipfile.ZipFile(pi_zip) as archive:
        rows = [json.loads(line) for line in archive.read('pi-traffic.jsonl').splitlines()]
    source = {(r['session_id'],r['sequence']) for r in rows if
              r.get('direction')=='TO_MCS' and r.get('forwarded') and r.get('kind')=='radio_receive'}
    with sqlite3.connect(db_path) as db:
        persisted = db.execute("SELECT session_id, sequence FROM events WHERE kind='radio_receive' AND direction='RX'").fetchall()
    return dict(pi_proxy_forwarded_radio_frames=len(source), mcs_db_radio_records=len(persisted),
                missing_from_db=[list(x) for x in sorted(source-set(persisted))],
                extra_in_db=[list(x) for x in sorted(set(persisted)-source)],
                duplicate_db_records=len(persisted)-len(set(persisted)),
                status=('COMPLETE' if source and source==set(persisted) and len(persisted)==len(set(persisted))
                        else 'INCOMPLETE' if not source else 'MISMATCH'),
                scope='Native service→Pi proxy→MCS DB; not a radio transmitter packet count')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', default='evidence-plan.local.json')
    parser.add_argument('--output', default='evidence-results')
    parser.add_argument('--offscreen', action='store_true', help='CI validation; does not measure a visible desktop')
    args = parser.parse_args()
    plan = validate_plan(json.loads(Path(args.plan).read_text(encoding='utf-8')))
    if args.offscreen:
        os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from evidence_suite.gui_probe import Bridge, MeasuredWindow
    run_id = str(uuid.uuid4())
    root = Path(args.output)/run_id
    root.mkdir(parents=True)
    sanitized = {k:v for k,v in plan.items() if k!='token'}
    dump(root/'plan.json', sanitized)
    dump(root/'manifest.json', dict(run_id=run_id, environment=environment(),
        offscreen=args.offscreen, architecture='Existing GUI thread polls ZeroMQ and writes SQLite synchronously; '
        'runner orchestration is a separate thread. No claim of worker-isolated MCS I/O.',
        hypothesis_note='COMPLETE means collection completed, not that a research hypothesis is proven.'))
    app = QApplication([])
    bridge = Bridge()
    stream = (root/'mcs-metrics.jsonl').open('w',encoding='utf-8')
    bind = plan.get('mcs_bind','tcp://*:5557')
    window = MeasuredWindow(bind, str(root/'mcs'), stream)
    resources = ResourceSampler(root/'pc-resources.jsonl', lambda:window.phase)
    window.show()
    remote = Remote(plan)
    result = {'run_id': run_id, 'tests': [], 'errors': []}
    done = threading.Event()
    def call(fn):
        return bridge.call(fn)
    def wait(predicate, timeout):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            if call(predicate):
                return True
            time.sleep(.02)
        return False
    def phase(name):
        remote.call('phase', {'phase':name})
        return call(lambda:window.begin_phase(name))
    def command(step):
        payload = bytes.fromhex(step['payload_hex'])
        return call(lambda:window.controller.transmit(payload))
    def execute():
        started = False
        try:
            endpoint = f"tcp://{plan['mcs_host']}:{int(plan.get('mcs_port',5557))}"
            info = remote.call('start', {'run_id':run_id, 'mcs_endpoint':endpoint})
            started = True
            result['pi'] = info
            dump(root/'pi-info.json', info)
            if info['mock']:
                result['provenance']='MOCK_VALIDATION_ONLY'
            else:
                result['provenance']='OPERATOR_DECLARED_NATIVE_REQUIRES_HARDWARE_CONFIRMATION'
            timeout = float(plan.get('timeout_s',8))
            connected = wait(lambda:window.controller.fresh, timeout)
            result['native_connected'] = connected
            steps = plan.get('h3',{}).get('steps',[])
            repeats = int(plan.get('h3',{}).get('repeats',3))
            # H1: measured native traffic and configured command loads, not invented RX rates.
            for repeat in range(int(plan.get('h1',{}).get('repeats',3))):
                for config in plan.get('h1',{}).get('phases',[]):
                    name = f"H1-{repeat+1}-{config['name']}"
                    if not connected or (float(config['command_hz'])>0 and not steps):
                        result['tests'].append(dict(test=name,status='BLOCKED',reason='No native Status or no configured command payload'))
                        continue
                    index = phase(name)
                    commands = []
                    errors = []
                    begin = time.monotonic()
                    next_send = begin
                    rate = float(config['command_hz'])
                    while time.monotonic()-begin<float(config['duration_s']):
                        now=time.monotonic()
                        if rate and now>=next_send:
                            try:
                                commands.append(command(steps[0]))
                            except Exception as exc:
                                errors.append(str(exc))
                            next_send=max(next_send+1/rate,now)
                        time.sleep(.005)
                    wait(lambda:all(window.controller.commands[c].state not in ('SENT','ACCEPTED')
                                    for c in commands),timeout)
                    summary=call(lambda:window.phase_stats(index))
                    states=call(lambda:{c:window.controller.commands[c].state for c in commands})
                    summary.update(test=name,status='COMPLETE' if summary['radio_receive'] else 'INCOMPLETE',
                                   observed_duration_s=time.monotonic()-begin,
                                   requested_command_hz=rate, command_states=states, send_errors=errors)
                    result['tests'].append(summary)
            # H3: sequential native commands with explicit expected-response matching.
            if not steps or not connected:
                result['tests'].append(dict(test='H3',status='BLOCKED',reason='Configure approved command and expected RX bytes; valid native Status required'))
            else:
                for repeat in range(repeats):
                    name=f'H3-{repeat+1}'
                    phase(name)
                    records=[]
                    for number, step in enumerate(steps):
                        before=call(lambda:len(window.rx))
                        record=dict(step=number+1, name=step.get('name',str(number+1)),payload_hex=step['payload_hex'])
                        try:
                            cmd=command(step)
                            record['command_id']=cmd
                            expected=step.get('expected_rx_hex')
                            expected=bytes.fromhex(expected).hex() if expected is not None else None
                            settled=wait(lambda:window.controller.commands[cmd].state not in ('SENT','ACCEPTED'),timeout)
                            record['state']=call(lambda:window.controller.commands[cmd].state)
                            if expected is None:
                                record.update(status='INCOMPLETE',reason='No expected response rule configured')
                            else:
                                matched=wait(lambda:any(r['payload_hex']==expected for r in window.rx[before:]),timeout)
                                matches=call(lambda:[r for r in window.rx[before:] if r['payload_hex']==expected])
                                record.update(status='COMPLETE' if matched and settled and record['state']=='TX_COMPLETED' else 'FAIL',
                                              expected_rx_hex=expected,matched_events=matches,
                                              matching_rule='Exact payload after submission, one command at a time; not protocol-native response ID correlation')
                        except Exception as exc:
                            record.update(status='FAIL',error=str(exc))
                        records.append(record)
                        time.sleep(max(0,min(float(step.get('delay_s',.2)),30)))
                    result['tests'].append(dict(test=name,status='COMPLETE' if all(r['status']=='COMPLETE' for r in records) else 'INCOMPLETE',steps=records))
            # H2 isolated endpoint: no RF packets or modem changes are issued.
            from evidence_suite.benchmark import run_case
            phase('H2')
            bench=remote.call('bench')
            host=urllib.parse.urlparse(plan['pi_url']).hostname
            config=plan.get('h2',{})
            profiles=config.get('profiles') or [dict(rate_hz=config['rate_hz'],payload_bytes=config['payload_bytes'])]
            for repeat in range(int(config.get('repeats',3))):
                for profile_number,profile in enumerate(profiles):
                    for protocol in ('zeromq','mqtt_qos0','mqtt_qos1'):
                        name=f'H2-{repeat+1}-profile{profile_number+1}-{protocol}'
                        try:
                            phase(name)
                            if protocol.startswith('mqtt') and bench.get('mqtt_error'):
                                raise RuntimeError(bench['mqtt_error'])
                            summary=run_case(host,info,run_id,protocol,{**config,**profile},root/name)
                            summary['test']=name
                            result['tests'].append(summary)
                        except Exception as exc:
                            result['tests'].append(dict(test=name,status='BLOCKED',reason=str(exc)))
        except Exception as exc:
            result['errors'].append(f'{type(exc).__name__}: {exc}')
            (root/'exception.txt').write_text(traceback.format_exc())
        finally:
            if started:
                try:
                    call(lambda:setattr(window,'phase','DRAIN'))
                    body=remote.call('finish',binary=True)
                    (root/'pi-evidence.zip').write_bytes(body)
                    result['pi_logs_recovered']=True
                    time.sleep(.3)
                except Exception as exc:
                    result['pi_logs_recovered']=False
                    result['errors'].append('Pi log recovery: '+str(exc))
            try:
                probe_error=call(lambda:getattr(window,'probe_error',None))
                if probe_error:
                    result['errors'].append('GUI/recording error: '+probe_error)
                call(window.close)
            except Exception as exc:
                result['errors'].append('MCS close: '+str(exc))
            stream.flush()
            stream.close()
            resources.close()
            if result.get('pi_logs_recovered'):
                try:
                    result['packet_reconciliation']=reconcile(root/'pi-evidence.zip',next((root/'mcs').glob('*.db')))
                except Exception as exc:
                    result['errors'].append('Reconciliation: '+str(exc))
            result['status']='COMPLETE' if (result['tests'] and all(t['status']=='COMPLETE' for t in result['tests'])
                and not result['errors'] and result.get('packet_reconciliation',{}).get('status')=='COMPLETE') else 'INCOMPLETE'
            dump(root/'summary.json',result)
            with (root/'summary.csv').open('w',newline='') as file:
                writer=csv.DictWriter(file,fieldnames=[
                    'test','status','radio_receive','gui_lateness_p95_ms','gui_tick_cost_p95_ms',
                    'log_cost_p95_ms','offered','locally_accepted','unique_echoes','missing_offered',
                    'missing_accepted','duplicate_echoes','stable_rtt_p95_ms','recovery_ms',
                    'completed_steps','total_steps','details_json'])
                writer.writeheader()
                for item in result['tests']:
                    row={k:item.get(k,'') for k in writer.fieldnames}
                    for source,column in [('gui_lateness_ms','gui_lateness_p95_ms'),
                                          ('gui_tick_cost_ms','gui_tick_cost_p95_ms'),
                                          ('log_cost_ms','log_cost_p95_ms')]:
                        row[column]=item.get(source,{}).get('p95','')
                    row['stable_rtt_p95_ms']=item.get('rtt_ms',{}).get('stable',{}).get('p95','')
                    row['completed_steps']=sum(s['status']=='COMPLETE' for s in item.get('steps',[]))
                    row['total_steps']=len(item.get('steps',[]))
                    row['details_json']=json.dumps(item)
                    writer.writerow(row)
            dump(root/'sha256.json',hashes(root))
            archive=root.with_suffix('.zip')
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as file:
                for p in sorted(root.rglob('*')):
                    if p.is_file():
                        file.write(p,p.relative_to(root))
            print(f"{result['status']}: {archive}",flush=True)
            done.set()
            bridge.requested.emit((app.quit,Future()))
    # Keep the Qt event loop alive when the measurement window is closed for packaging.
    app.setQuitOnLastWindowClosed(False)
    thread=threading.Thread(target=execute,daemon=True)
    QTimer.singleShot(0,thread.start)
    app.exec()
    if not done.is_set():
        print('Measurement window closed before completion; partial files remain in',root)
        return 2
    return 0 if result['status']=='COMPLETE' else 2


if __name__=='__main__':
    raise SystemExit(main())
