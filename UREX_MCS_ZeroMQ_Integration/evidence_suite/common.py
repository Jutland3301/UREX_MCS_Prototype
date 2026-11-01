from __future__ import annotations
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import platform
import subprocess
import sys
import time
import threading
from pathlib import Path


def environment():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = 'unknown', None
    packages = {}
    for name in ('pyzmq', 'protobuf', 'PySide6', 'paho-mqtt', 'amqtt', 'psutil'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return dict(python=sys.version, platform=platform.platform(), commit=commit, packages=packages,
                working_tree_dirty=dirty, utc_unix_ms=time.time_ns() // 1_000_000)


def dump(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values)-1)*q
    lo = int(pos)
    return values[lo] + (values[min(lo+1, len(values)-1)]-values[lo])*(pos-lo)


def stats(values):
    return dict(n=len(values), median=percentile(values, .5), p95=percentile(values, .95),
                maximum=max(values) if values else None)


def hashes(directory):
    root = Path(directory)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'sha256.json'}


def validate_plan(plan):
    for key in ('pi_url', 'token', 'mcs_host'):
        if not isinstance(plan.get(key), str) or not plan[key] or 'CHANGE_ME' in plan[key]:
            raise ValueError(f'Set {key} in the plan before running')
    if not 0 < float(plan.get('timeout_s', 8)) <= 120:
        raise ValueError('timeout_s must be in (0,120]')
    h1 = plan.get('h1', {})
    if not h1.get('phases') or not 1 <= int(h1.get('repeats', 3)) <= 20:
        raise ValueError('Configure at least one H1 phase and 1–20 repeats')
    for phase in h1.get('phases', []):
        if not 0 < float(phase['duration_s']) <= 600 or not 0 <= float(phase['command_hz']) <= 100:
            raise ValueError('H1 duration or command rate outside supported range')
    h3 = plan.get('h3', {})
    if not 1 <= int(h3.get('repeats', 3)) <= 20:
        raise ValueError('H3 repeats must be 1–20')
    for step in h3.get('steps', []):
        if not bytes.fromhex(step['payload_hex']):
            raise ValueError('Each command needs a nonempty payload')
        if step.get('expected_rx_hex') is not None:
            bytes.fromhex(step['expected_rx_hex'])
    h2 = plan.get('h2', {})
    for key, low, high in [('duration_s', .4, 120), ('rate_hz', 1, 1000), ('payload_bytes', 24, 4096)]:
        if not low <= float(h2.get(key, {'duration_s': 15, 'rate_hz': 100, 'payload_bytes': 128}[key])) <= high:
            raise ValueError(f'H2 {key} outside [{low}, {high}]')
    if not 1 <= int(h2.get('repeats', 3)) <= 20:
        raise ValueError('H2 repeats must be 1–20')
    for profile in h2.get('profiles', []):
        if not 1 <= float(profile['rate_hz']) <= 1000 or not 24 <= int(profile['payload_bytes']) <= 4096:
            raise ValueError('H2 profile rate or payload size outside supported range')
    return plan


class ResourceSampler:
    """One-second process/child CPU and RSS samples; CPU percent uses one core=100%."""
    def __init__(self, path, phase):
        self.path, self.phase = Path(path), phase
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        import psutil
        processes = {}
        with self.path.open('w') as stream:
            while not self.stop.is_set():
                try:
                    parent = psutil.Process()
                    samples = []
                    for item in [parent, *parent.children(recursive=True)]:
                        try:
                            process = processes.setdefault(item.pid, item)
                            samples.append(dict(pid=process.pid, name=process.name(),
                                cpu_percent=process.cpu_percent(None), rss_bytes=process.memory_info().rss))
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    stream.write(json.dumps(dict(phase=self.phase(), local_unix_ms=time.time_ns()//1_000_000,
                        processes=samples, cpu_note='one core=100%; first sample per process is warm-up'))+'\n')
                    stream.flush()
                except Exception as exc:
                    stream.write(json.dumps(dict(error=str(exc)))+'\n')
                self.stop.wait(1)

    def close(self):
        self.stop.set()
        self.thread.join(3)
