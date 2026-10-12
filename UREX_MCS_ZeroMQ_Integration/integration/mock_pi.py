"""Run only synthetic Pi backend: python -m integration.mock_pi."""
import argparse
import signal
import time

from integration.backend import MockBackend
from integration.engine import PiEngine
from integration.transport import ZmqTransport


def main():
    parser = argparse.ArgumentParser(description="MOCK Pi — no hardware driver")
    parser.add_argument("--connect", default="tcp://127.0.0.1:5557")
    parser.add_argument("--mode", choices=["success", "fail", "timeout"], default="success")
    parser.add_argument("--payload-limit", type=int, default=63)
    parser.add_argument("--log-dir", default="logs/mock-pi")
    args = parser.parse_args()
    if not 1 <= args.payload_limit <= 65000:
        parser.error("payload limit must fit the integration body; use 1–65000")
    transport = ZmqTransport(args.connect, pi=True)
    engine = PiEngine(transport, MockBackend(limit=args.payload_limit, mode=args.mode), log_dir=args.log_dir)
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"MOCK Pi connecting to {args.connect}; mode={args.mode}; no real radio")
    try:
        transport.start()
        while running:
            engine.tick()
            time.sleep(0.01)
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
