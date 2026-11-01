"""Matched PC↔Pi echo workload; local monotonic RTT, controlled client outage."""
from __future__ import annotations
import json
import struct
import threading
import time
import uuid
from pathlib import Path
import zmq
from evidence_suite.common import stats

HEADER = struct.Struct('!QQ')  # Sequence + PC monotonic send timestamp.


class ZmqClient:
    def __init__(self, host, port, *_):
        self.endpoint = f'tcp://{host}:{port}'
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.IMMEDIATE, 1)
        self.socket.setsockopt(zmq.SNDHWM, 10000)
        self.socket.setsockopt(zmq.RCVHWM, 10000)
        self.socket.connect(self.endpoint)
    def send(self, payload):
        try:
            self.socket.send(payload, zmq.DONTWAIT)
            return True
        except zmq.Again:
            return False
    def receive(self):
        result = []
        for _ in range(10000):
            try:
                result.append(self.socket.recv(zmq.DONTWAIT))
            except zmq.Again:
                break
        return result
    def disconnect(self):
        self.socket.disconnect(self.endpoint)
    def reconnect(self):
        self.socket.connect(self.endpoint)
    def close(self):
        self.socket.close()
        self.context.term()


class MqttClient:
    def __init__(self, host, port, run_id, qos):
        import paho.mqtt.client as mqtt
        from queue import Queue
        self.queue = Queue()
        self.ready = threading.Event()
        self.host, self.port, self.qos = host, port, qos
        identifier = uuid.uuid4().hex
        self.request = f'urex/{run_id}/request/{identifier}'
        self.response = f'urex/{run_id}/response/{identifier}'
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=identifier,
                                  clean_session=False, protocol=mqtt.MQTTv311)
        self.client.max_queued_messages_set(10000)
        self.client.max_inflight_messages_set(1000)
        def connected(c, userdata, flags, reason, properties):
            if not reason.is_failure:
                c.subscribe(self.response, qos=qos)
        self.client.on_connect = connected
        self.client.on_subscribe = lambda *_: self.ready.set()
        self.client.on_message = lambda c, u, m: self.queue.put(bytes(m.payload))
        self.client.connect(host, port, keepalive=10)
        self.client.loop_start()
        if not self.ready.wait(5):
            self.close()
            raise RuntimeError('MQTT subscription timeout')
    def send(self, payload):
        import paho.mqtt.client as mqtt
        info = self.client.publish(self.request, payload, qos=self.qos)
        # QoS1 can be accepted into the local outgoing queue while disconnected.
        return info.rc == mqtt.MQTT_ERR_SUCCESS or (
            self.qos == 1 and info.rc == mqtt.MQTT_ERR_NO_CONN)
    def receive(self):
        from queue import Empty
        result = []
        while True:
            try:
                result.append(self.queue.get_nowait())
            except Empty:
                return result
    def disconnect(self):
        self.ready.clear()
        self.client.disconnect()
        self.client.loop_stop()
    def reconnect(self):
        self.client.reconnect()
        self.client.loop_start()
        # Do not block; time until usable subscription/echo is measured by caller.
    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


def run_case(host, ports, run_id, protocol, config, directory):
    rate = float(config['rate_hz'])
    duration = float(config['duration_s'])
    size = int(config['payload_bytes'])
    outage_at = duration*.4
    outage_s = min(float(config.get('outage_s', 2)), duration*.25)
    drain_s = float(config.get('drain_s', 3))
    if not 0 <= drain_s <= 30:
        raise ValueError('drain_s must be in [0,30]')
    client = (ZmqClient(host, ports['bench_port']) if protocol == 'zeromq' else
              MqttClient(host, ports['mqtt_port'], run_id, 1 if protocol == 'mqtt_qos1' else 0))
    sent, accepted, seen = {}, {}, set()
    rtts = {'stable': [], 'outage': [], 'post_reconnect': []}
    duplicates = reordered = corrupt = 0
    last = 0
    recovery_ms = None
    disconnected = reconnected = False
    actual_reconnect = None
    sequence = 0
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    try:
        # Both technologies receive a warm-up window, excluded from measurement.
        time.sleep(.3)
        start = time.perf_counter()
        next_send = start
        with (path/'samples.jsonl').open('w') as stream:
            while True:
                now = time.perf_counter()
                elapsed = now-start
                if elapsed >= outage_at and not disconnected:
                    client.disconnect()
                    disconnected = True
                    stream.write(json.dumps(dict(event='disconnect', elapsed_s=elapsed))+'\n')
                if elapsed >= outage_at+outage_s and not reconnected:
                    client.reconnect()
                    actual_reconnect = time.perf_counter()
                    reconnected = True
                    stream.write(json.dumps(dict(event='reconnect_requested', elapsed_s=elapsed))+'\n')
                if elapsed < duration and now >= next_send:
                    sequence += 1
                    stamp = time.perf_counter_ns()
                    phase = ('stable' if not disconnected else 'outage' if not reconnected else 'post_reconnect')
                    payload = HEADER.pack(sequence, stamp) + b'x'*(size-HEADER.size)
                    ok = client.send(payload)
                    sent[sequence] = (stamp, phase)
                    accepted[sequence] = ok
                    stream.write(json.dumps(dict(event='send', sequence=sequence, monotonic_ns=stamp,
                                                 phase=phase, accepted=ok))+'\n')
                    # Avoid catch-up bursts if the PC is overloaded.
                    next_send = max(next_send+1/rate, now)
                for payload in client.receive():
                    stamp = time.perf_counter_ns()
                    if len(payload) != size or len(payload) < HEADER.size:
                        corrupt += 1
                        continue
                    seq, original_stamp = HEADER.unpack_from(payload)
                    if (seq not in sent or original_stamp != sent[seq][0]
                            or payload[HEADER.size:] != b'x'*(size-HEADER.size)):
                        corrupt += 1
                        continue
                    duplicate = seq in seen
                    if duplicate:
                        duplicates += 1
                    else:
                        if seq < last:
                            reordered += 1
                        last = max(last, seq)
                        seen.add(seq)
                        rtts[sent[seq][1]].append((stamp-original_stamp)/1e6)
                    if reconnected and recovery_ms is None and sent[seq][0] >= int(actual_reconnect*1e9):
                        recovery_ms = (stamp/1e9-actual_reconnect)*1000
                    stream.write(json.dumps(dict(event='receive', sequence=seq, duplicate=duplicate,
                        monotonic_ns=stamp, rtt_ms=(stamp-original_stamp)/1e6))+'\n')
                if elapsed >= duration+drain_s:
                    break
                time.sleep(.001)
        accepted_count = sum(accepted.values())
        return dict(status='COMPLETE' if sent and seen else 'INCOMPLETE', protocol=protocol,
                    scope='PC_PI_SOFTWARE_ECHO_NOT_RF', qos=(1 if protocol=='mqtt_qos1' else 0),
                    clean_session=False if protocol.startswith('mqtt') else None,
                    offered=len(sent), locally_accepted=accepted_count, unique_echoes=len(seen),
                    missing_offered=len(set(sent)-seen), missing_accepted=len(
                        {s for s, ok in accepted.items() if ok}-seen),
                    duplicate_echoes=duplicates, reordered_echoes=reordered, corrupt=corrupt,
                    rtt_ms={k:stats(v) for k,v in rtts.items()}, recovery_ms=recovery_ms,
                    elapsed_s=time.perf_counter()-start, requested_rate_hz=rate,
                    payload_bytes=size, outage_s=outage_s,
                    outage_definition='PC client intentionally disconnects, continues publishing, then reconnects; '
                    'QoS1 uses bounded Paho offline queue; ZeroMQ IMMEDIATE rejects unavailable sends. '
                    'This is not packet-loss injection or a physical cable failure.')
    finally:
        client.close()
