from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from communication.simulated_transport import SimulatedTransport
from measurement.metrics_collector import MetricsCollector
from packet.encoder import PacketEncoder
from packet.parser import PacketParser
from packet.profiles import PROVISIONAL_PROFILE
from simulator.manual_packet_source import ManualPacketSource
from simulator.scenario_config import ScenarioConfig
from simulator.scenario_controller import ExperimentState, ScenarioController


def run(config: ScenarioConfig) -> dict[str, object]:
    source = ManualPacketSource(PROVISIONAL_PROFILE, config)
    encoder = PacketEncoder(PROVISIONAL_PROFILE)
    parser = PacketParser(PROVISIONAL_PROFILE)
    transport = SimulatedTransport(
        config.network,
        random_seed=config.random_seed,
    )
    metrics = MetricsCollector()
    transport.set_event_handler(metrics.record_transport_event)
    transport.set_message_handler(
        lambda raw: metrics.record_parse_result(parser.parse(raw))
    )
    transport.start()
    controller = ScenarioController(source, encoder, transport, metrics)
    controller.start(
        config.experiment.duration_s,
        config.experiment.burst_size,
    )

    interval_s = config.experiment.scheduler_interval_ms / 1000.0
    while controller.state == ExperimentState.RUNNING:
        controller.tick()
        time.sleep(interval_s)
    # Deliver packets whose configured delay ends just after the generation run.
    drain_deadline = time.monotonic() + max(
        1.0,
        (config.network.delay_ms + config.network.jitter_ms) / 1000.0 + 0.1,
    )
    while transport.queue_depth and time.monotonic() < drain_deadline:
        transport.poll()
        time.sleep(min(interval_s, 0.02))

    return asdict(metrics.snapshot(transport.queue_depth))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an UREX experiment without GUI")
    parser.add_argument(
        "--scenario",
        default="scenarios/default.json",
        help="scenario JSON path",
    )
    parser.add_argument("--duration", type=float, help="override duration in seconds")
    parser.add_argument("--burst", type=int, help="override burst size")
    parser.add_argument("--drop", type=float, help="override drop percentage")
    parser.add_argument("--corrupt", type=float, help="override corruption percentage")
    parser.add_argument("--delay", type=float, help="override fixed delay in ms")
    parser.add_argument("--jitter", type=float, help="override delay jitter in ms")
    parser.add_argument("--output", help="optional JSON result path")
    args = parser.parse_args()

    config = ScenarioConfig.load(args.scenario)
    if args.duration is not None:
        config.experiment.duration_s = args.duration
    if args.burst is not None:
        config.experiment.burst_size = args.burst
    if args.drop is not None:
        config.network.drop_rate_percent = args.drop
    if args.corrupt is not None:
        config.network.corruption_rate_percent = args.corrupt
    if args.delay is not None:
        config.network.delay_ms = args.delay
    if args.jitter is not None:
        config.network.jitter_ms = args.jitter
    config.validate()

    result = run(config)
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
