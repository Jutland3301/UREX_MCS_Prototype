"""Pi-side coordinator, native-service traffic recorder and middleware echo peer."""
from __future__ import annotations
import argparse
import asyncio
import hmac
import io
import json
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import zmq
from integration.codec import decode
from integration.transport import ZmqTransport
from evidence_suite.common import dump, environment, hashes, ResourceSampler


class PiSession:
    def __init__(self, args, request):
        self.args = args
        self.started_at = time.monotonic()
        self.run_id = str(uuid.UUID(request['run_id']))
        self.directory = Path(args.output) / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stop = threading.Event()
        self.phase = 'STARTUP'
        self.ready = threading.Event()
        self.error = None
        self.process = None
        self.broker = None
        self.broker_loop = None
        self.mqtt_client = None
        self.mqtt_ready = threading.Event()
        self.mqtt_error = None
        self.control = request
        self.resources = ResourceSampler(self.directory/'pi-resources.jsonl', lambda:self.phase)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        if not self.ready.wait(10):
            self.stop.set()
            raise RuntimeError('Pi proxy startup timeout')
        if self.error:
            self.resources.close()
            raise RuntimeError(self.error)

    def trace(self, stream, direction, frame, success=True):
        try:
            packet = decode(frame)
            record = dict(session_id=packet.session_id, sequence=packet.sequence,
                          kind=packet.WhichOneof('body'))
        except ValueError as exc:
            record = dict(decode_error=str(exc))
        record.update(direction=direction, forwarded=success, phase=self.phase,
                      local_unix_ms=time.time_ns()//1_000_000,
                      monotonic_ns=time.perf_counter_ns(), frame_hex=frame.hex())
        stream.write(json.dumps(record)+'\n')
        stream.flush()

    def run(self):
        upstream = downstream = None
        raw = self.directory / 'pi-traffic.jsonl'
        try:
            upstream = ZmqTransport(self.control['mcs_endpoint'], pi=True)
            downstream = ZmqTransport(self.args.native_bind)
            upstream.start()
            downstream.start()
            with raw.open('w', encoding='utf-8') as stream:
                def forward(target, direction, frame):
                    try:
                        target.send(frame)
                    except ConnectionError:
                        self.trace(stream, direction, frame, False)
                    else:
                        self.trace(stream, direction, frame)
                upstream.set_message_handler(lambda f: forward(downstream, 'TO_NATIVE', f))
                downstream.set_message_handler(lambda f: forward(upstream, 'TO_MCS', f))
                self.start_native()
                self.ready.set()
                while not self.stop.is_set():
                    upstream.poll()
                    downstream.poll()
                    time.sleep(.001)
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'
            self.ready.set()
        finally:
            if upstream is not None:
                upstream.stop()
            if downstream is not None:
                downstream.stop()

    def start_native(self):
        if self.args.mock:
            command = [sys.executable, '-m', 'integration.mock_pi', '--connect',
                       self.args.native_connect, '--log-dir', str(self.directory/'native')]
        elif self.args.native_command:
            command = json.loads(self.args.native_command)
            if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                raise ValueError('--native-command must be a JSON array of command arguments')
            command = [x.replace('{endpoint}', self.args.native_connect).replace(
                '{log_dir}', str(self.directory/'native')) for x in command]
        else:
            command = None  # Existing hardware service must connect to native_connect.
        dump(self.directory/'manifest.json', dict(
            run_id=self.run_id, environment=environment(), mock=self.args.mock,
            hardware_provenance='MOCK' if self.args.mock else 'OPERATOR_DECLARED_NATIVE',
            native_command=command, native_endpoint=self.args.native_connect,
            note='Pi proxy counts enqueue-to-ZeroMQ success, not RF delivery.'))
        if command:
            self.native_output = (self.directory/'native-process.log').open('wb')
            self.process = subprocess.Popen(command, stdout=self.native_output, stderr=subprocess.STDOUT)

    def start_bench(self):
        if hasattr(self, 'bench_thread'):
            return
        self.bench_ready = threading.Event()
        self.bench_thread = threading.Thread(target=self.bench_loop, daemon=True)
        self.bench_thread.start()
        if not self.bench_ready.wait(5):
            raise RuntimeError('ZeroMQ benchmark startup timeout')
        if getattr(self, 'bench_error', None):
            raise RuntimeError(self.bench_error)
        self.start_mqtt()

    def bench_loop(self):
        context = zmq.Context()
        socket = context.socket(zmq.ROUTER)
        socket.setsockopt(zmq.LINGER, 0)
        try:
            socket.bind(f'tcp://{"*" if self.args.bind == "0.0.0.0" else self.args.bind}:{self.args.bench_port}')
            self.bench_ready.set()
            with (self.directory/'pi-zmq-benchmark.jsonl').open('w') as stream:
                while not self.stop.is_set():
                    if not socket.poll(50):
                        continue
                    parts = socket.recv_multipart()
                    if len(parts) != 2:
                        continue
                    socket.send_multipart(parts)
                    stream.write(json.dumps(dict(local_unix_ms=time.time_ns()//1_000_000,
                                                 request_hex=parts[-1].hex()))+'\n')
        except Exception as exc:
            self.bench_error = str(exc)
            self.bench_ready.set()
        finally:
            socket.close()
            context.term()

    def start_mqtt(self):
        def broker_thread():
            from amqtt.broker import Broker
            loop = asyncio.new_event_loop()
            self.broker_loop = loop
            asyncio.set_event_loop(loop)
            async def serve():
                try:
                    self.broker = Broker({
                        'listeners': {'default': {'type': 'tcp', 'bind': f'{self.args.bind}:{self.args.mqtt_port}'}},
                        'plugins': {'amqtt.plugins.authentication.AnonymousAuthPlugin': {'allow_anonymous': True}}
                    })
                    await self.broker.start()
                    self.mqtt_ready.set()
                except Exception as exc:
                    self.mqtt_error = str(exc)
                    self.mqtt_ready.set()
            loop.run_until_complete(serve())
            if not self.mqtt_error:
                loop.run_forever()
            loop.close()
        self.broker_thread = threading.Thread(target=broker_thread, daemon=True)
        self.broker_thread.start()
        if not self.mqtt_ready.wait(8) or self.mqtt_error:
            self.mqtt_error = self.mqtt_error or 'Embedded broker startup timeout'
            return
        try:
            import paho.mqtt.client as mqtt
            self.mqtt_stream = (self.directory/'pi-mqtt-benchmark.jsonl').open('w')
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id='pi-echo-'+self.run_id, clean_session=False,
                                 protocol=mqtt.MQTTv311)
            subscribed = threading.Event()
            def on_connect(c, userdata, flags, reason, properties):
                if not reason.is_failure:
                    c.subscribe(f'urex/{self.run_id}/request/+', qos=1)
            def on_message(c, userdata, message):
                suffix = message.topic.rsplit('/', 1)[-1]
                c.publish(f'urex/{self.run_id}/response/{suffix}', message.payload, qos=message.qos)
                self.mqtt_stream.write(json.dumps(dict(local_unix_ms=time.time_ns()//1_000_000,
                    qos=message.qos, duplicate=message.dup, request_hex=message.payload.hex()))+'\n')
            client.on_connect = on_connect
            client.on_subscribe = lambda *_: subscribed.set()
            client.on_message = on_message
            client.connect('127.0.0.1', self.args.mqtt_port, keepalive=10)
            client.loop_start()
            self.mqtt_client = client
            if not subscribed.wait(5):
                raise RuntimeError('MQTT echo subscription timeout')
        except Exception as exc:
            self.mqtt_error = str(exc)

    def finish(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        # Drain messages already emitted by the native service before stopping the proxy.
        time.sleep(.2)
        self.stop.set()
        self.thread.join(5)
        if hasattr(self, 'bench_thread'):
            self.bench_thread.join(5)
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
        if hasattr(self, 'mqtt_stream'):
            self.mqtt_stream.close()
        if self.broker_loop and self.broker_loop.is_running():
            if self.broker:
                future = asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.broker_loop)
                try:
                    future.result(5)
                except Exception as exc:
                    self.mqtt_error = str(exc)
            self.broker_loop.call_soon_threadsafe(self.broker_loop.stop)
            self.broker_thread.join(5)
        if hasattr(self, 'native_output'):
            self.native_output.close()
        self.resources.close()
        dump(self.directory/'end.json', dict(error=self.error, mqtt_error=self.mqtt_error,
             proxy_stopped=not self.thread.is_alive(), native_returncode=(
                 self.process.returncode if self.process else None)))
        dump(self.directory/'sha256.json', hashes(self.directory))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(self.directory.rglob('*')):
                if p.is_file():
                    archive.write(p, p.relative_to(self.directory))
        return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--bench-port', type=int, default=5559)
    parser.add_argument('--mqtt-port', type=int, default=18884)
    parser.add_argument('--native-bind', default='tcp://*:5558')
    parser.add_argument('--native-connect', default='tcp://127.0.0.1:5558')
    parser.add_argument('--native-command', help='JSON argv, with {endpoint} and {log_dir} placeholders')
    parser.add_argument('--mock', action='store_true', help='Validation ONLY; marks every result as mock')
    parser.add_argument('--token', default=None)
    parser.add_argument('--output', default='evidence-pi')
    args = parser.parse_args()
    token = args.token or secrets.token_urlsafe(24)
    state = {'session': None}
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token):
                self.send_error(401)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 65536:
                    raise ValueError('Request too large')
                request = json.loads(self.rfile.read(length) or b'{}')
                with lock:
                    session = state['session']
                    if self.path == '/start':
                        if session:
                            raise RuntimeError('A session is already active')
                        session = PiSession(args, request)
                        state['session'] = session
                        result = dict(mock=args.mock, environment=environment(), bench_port=args.bench_port,
                                      mqtt_port=args.mqtt_port, native_endpoint=args.native_connect)
                    elif self.path == '/phase':
                        if session is None:
                            raise RuntimeError('No active session')
                        session.phase = str(request['phase'])[:100]
                        result = dict(error=session.error)
                    elif self.path == '/bench':
                        if session is None:
                            raise RuntimeError('No active session')
                        session.start_bench()
                        result = dict(mqtt_error=session.mqtt_error)
                    elif self.path == '/finish':
                        if session is None:
                            raise RuntimeError('No active session')
                        body = session.finish()
                        state['session'] = None
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/zip')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    else:
                        self.send_error(404)
                        return
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({'error': f'{type(exc).__name__}: {exc}'}).encode()
                self.send_response(400)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    # A lost PC cannot leave radio commands running: commands are initiated only by PC.
    # Agent/proxy expires idle sessions after the bounded maximum suite duration.
    def watchdog():
        while True:
            time.sleep(5)
            with lock:
                session = state['session']
                if session and time.monotonic()-session.started_at > 3600:
                    session.finish()
                    state['session'] = None
    threading.Thread(target=watchdog, daemon=True).start()
    print(f'Pi agent listening on {args.bind}:{args.port}; token={token}', flush=True)
    print(f'Native hardware service must connect to {args.native_connect}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if state['session']:
            state['session'].finish()
        server.server_close()


if __name__ == '__main__':
    main()
