"""End-to-end loopback validation. Results always labelled MOCK, never hardware evidence."""
from __future__ import annotations
import argparse
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='evidence-selftest')
    args=parser.parse_args()
    output=Path(args.output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    # Reserve distinct free TCP ports; agent/runner are launched together in this process namespace.
    sockets=[]
    for _ in range(5):
        s=socket.socket();s.bind(('0.0.0.0',0));sockets.append(s)
    control,native,bench,mqtt,mcs=[s.getsockname()[1] for s in sockets]
    for s in sockets:s.close()
    token='selftest-only-token'
    plan=dict(pi_url=f'http://127.0.0.1:{control}',token=token,mcs_host='127.0.0.1',
        mcs_bind=f'tcp://*:{mcs}',mcs_port=mcs,timeout_s=2,
        h1=dict(repeats=1,phases=[dict(name='concurrent',duration_s=1,command_hz=3)]),
        h2=dict(repeats=1,duration_s=1.2,rate_hz=20,payload_bytes=64,outage_s=.2,drain_s=.7),
        h3=dict(repeats=2,steps=[dict(name='MOCK-echo',payload_hex='000aff',expected_rx_hex='000aff',delay_s=.01)]))
    planfile=output/'selftest-plan.json'
    planfile.write_text(json.dumps(plan))
    agent=subprocess.Popen([sys.executable,'-m','evidence_suite.agent','--mock','--token',token,
        '--port',str(control),'--bench-port',str(bench),'--mqtt-port',str(mqtt),
        '--native-bind',f'tcp://*:{native}','--native-connect',f'tcp://127.0.0.1:{native}',
        '--output',str(output/'pi')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        first=agent.stdout.readline()
        if 'listening' not in first:raise RuntimeError('Agent did not start: '+first)
        completed=subprocess.run([sys.executable,'-m','evidence_suite.run','--plan',str(planfile),
            '--output',str(output/'pc'),'--offscreen'],timeout=80)
        summaries=sorted((output/'pc').glob('*/summary.json'),key=lambda p:p.stat().st_mtime)
        summary=json.loads(summaries[-1].read_text())
        assert completed.returncode==0,summary
        assert summary['provenance']=='MOCK_VALIDATION_ONLY'
        assert summary['pi_logs_recovered']
        assert len(summary['tests'])==6
        assert {r.get('protocol') for r in summary['tests'] if r['test'].startswith('H2')}=={'zeromq','mqtt_qos0','mqtt_qos1'}
        assert summary['packet_reconciliation']['status']=='COMPLETE'
        assert all(r['status']=='COMPLETE' for r in summary['tests'])
        print('SELFTEST PASS — MOCK ONLY; all six collections, reconciliation and ZIP recovery checked')
    finally:
        agent.terminate()
        try:agent.wait(5)
        except subprocess.TimeoutExpired:agent.kill();agent.wait()
        (output/'agent-console.log').write_text(agent.stdout.read(),encoding='utf-8')


if __name__=='__main__':main()
