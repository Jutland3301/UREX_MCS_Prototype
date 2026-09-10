from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from communication.simulated_transport import SimulatedTransport
from measurement.metrics_collector import MetricsCollector
from packet.encoder import PacketEncoder
from packet.parser import PacketParser
from packet.profiles import PROVISIONAL_PROFILE
from simulator.manual_packet_source import ManualPacketSource
from simulator.scenario_config import NetworkConditions, ScenarioConfig
from simulator.scenario_controller import ExperimentState, ScenarioController


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def default_config() -> ScenarioConfig:
    return ScenarioConfig.load("scenarios/default.json")


class ManualPacketSourceTests(unittest.TestCase):
    def test_manual_value_is_encoded_in_engineering_units(self) -> None:
        source = ManualPacketSource(PROVISIONAL_PROFILE, default_config())
        source.set_value("RADIO_STATUS", "rssi_dbm", "-91.25")
        raw = source.encode_once(
            "RADIO_STATUS",
            PacketEncoder(PROVISIONAL_PROFILE),
        )
        result = PacketParser(PROVISIONAL_PROFILE).parse(raw)
        self.assertTrue(result.ok, result.errors)
        assert result.packet is not None
        self.assertAlmostEqual(result.packet.fields["rssi_dbm"], -91.25)

    def test_enum_bool_and_range_validation(self) -> None:
        source = ManualPacketSource(PROVISIONAL_PROFILE, default_config())
        self.assertEqual(
            source.set_value("RADIO_STATUS", "state", "tx").value,
            "TX",
        )
        self.assertFalse(
            source.set_value("RADIO_STATUS", "lock_status", "false")
        )
        with self.assertRaises(ValueError):
            source.set_value("RPI_STATUS", "cpu_usage_percent", 150)

    def test_raw_hex_accepts_spacing_and_rejects_partial_byte(self) -> None:
        self.assertEqual(
            ManualPacketSource.decode_raw_hex("0x55 0x58 01"),
            b"UX\x01",
        )
        with self.assertRaises(ValueError):
            ManualPacketSource.decode_raw_hex("555")

    def test_edited_scenario_can_be_saved_and_loaded(self) -> None:
        config = default_config()
        source = ManualPacketSource(PROVISIONAL_PROFILE, config)
        source.set_value("RADIO_STATUS", "state", "TX")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            config.save(path)
            loaded = ScenarioConfig.load(path)
        self.assertEqual(loaded.packet_values["RADIO_STATUS"]["state"], "TX")


class SimulatedTransportTests(unittest.TestCase):
    def test_delay_holds_message_until_due(self) -> None:
        clock = FakeClock()
        transport = SimulatedTransport(
            NetworkConditions(delay_ms=250.0),
            monotonic=clock,
        )
        received: list[bytes] = []
        transport.set_message_handler(received.append)
        transport.start()
        transport.submit_incoming(b"packet")
        self.assertEqual(transport.poll(), 0)
        clock.advance(0.249)
        self.assertEqual(transport.poll(), 0)
        clock.advance(0.001)
        self.assertEqual(transport.poll(), 1)
        self.assertEqual(received, [b"packet"])

    def test_drop_and_corruption_events_are_observable(self) -> None:
        events: list[str] = []
        transport = SimulatedTransport(
            NetworkConditions(drop_rate_percent=100.0)
        )
        transport.set_event_handler(
            lambda event, _size, _latency: events.append(event)
        )
        transport.start()
        self.assertEqual(transport.submit_incoming(b"abc"), "dropped")
        self.assertEqual(events, ["dropped"])

        events.clear()
        transport.configure(NetworkConditions(corruption_rate_percent=100.0))
        self.assertEqual(transport.submit_incoming(b"abc"), "corrupted")
        self.assertIn("corrupted", events)

    def test_link_stop_counts_queued_packets_as_dropped(self) -> None:
        clock = FakeClock()
        events: list[str] = []
        transport = SimulatedTransport(
            NetworkConditions(delay_ms=1000.0),
            monotonic=clock,
        )
        transport.set_event_handler(
            lambda event, _size, _latency: events.append(event)
        )
        transport.start()
        transport.submit_incoming(b"abc")
        transport.stop()
        self.assertEqual(transport.queue_depth, 0)
        self.assertIn("dropped", events)


class ScenarioControllerTests(unittest.TestCase):
    def test_timed_experiment_generates_and_measures_packets(self) -> None:
        clock = FakeClock()
        config = default_config()
        for packet_name in config.update_periods_s:
            config.update_periods_s[packet_name] = 0.1
        source = ManualPacketSource(
            PROVISIONAL_PROFILE,
            config,
            monotonic=clock,
        )
        transport = SimulatedTransport(monotonic=clock)
        metrics = MetricsCollector(monotonic=clock)
        parser = PacketParser(PROVISIONAL_PROFILE)
        transport.set_event_handler(metrics.record_transport_event)
        transport.set_message_handler(
            lambda raw: metrics.record_parse_result(parser.parse(raw))
        )
        transport.start()
        controller = ScenarioController(
            source,
            PacketEncoder(PROVISIONAL_PROFILE),
            transport,
            metrics,
            monotonic=clock,
        )

        controller.start(duration_s=0.25, burst_size=2)
        controller.tick()
        clock.advance(0.1)
        controller.tick()
        clock.advance(0.1)
        controller.tick()
        clock.advance(0.05)
        controller.tick()

        snapshot = metrics.snapshot(transport.queue_depth)
        self.assertEqual(controller.state, ExperimentState.COMPLETED)
        self.assertEqual(snapshot.generated_packets, 30)
        self.assertEqual(snapshot.delivered_packets, 30)
        self.assertEqual(snapshot.parse_ok_packets, 30)
        self.assertGreater(snapshot.maximum_packet_size, 0)
        self.assertGreaterEqual(snapshot.maximum_packet_size, snapshot.minimum_packet_size)

    def test_forced_faults_update_metrics(self) -> None:
        clock = FakeClock()
        config = default_config()
        source = ManualPacketSource(PROVISIONAL_PROFILE, config, monotonic=clock)
        transport = SimulatedTransport(monotonic=clock)
        metrics = MetricsCollector(monotonic=clock)
        parser = PacketParser(PROVISIONAL_PROFILE)
        transport.set_event_handler(metrics.record_transport_event)
        transport.set_message_handler(
            lambda raw: metrics.record_parse_result(parser.parse(raw))
        )
        transport.start()
        controller = ScenarioController(
            source,
            PacketEncoder(PROVISIONAL_PROFILE),
            transport,
            metrics,
            monotonic=clock,
        )

        controller.send_once("RADIO_STATUS", force_drop=True)
        controller.send_once("RADIO_STATUS", force_corrupt=True)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.dropped_packets, 1)
        self.assertEqual(snapshot.corrupted_packets, 1)
        self.assertEqual(snapshot.parse_error_packets, 1)

    def test_pause_time_is_excluded_from_experiment_metrics(self) -> None:
        clock = FakeClock()
        config = default_config()
        source = ManualPacketSource(PROVISIONAL_PROFILE, config, monotonic=clock)
        transport = SimulatedTransport(monotonic=clock)
        metrics = MetricsCollector(monotonic=clock)
        controller = ScenarioController(
            source,
            PacketEncoder(PROVISIONAL_PROFILE),
            transport,
            metrics,
            monotonic=clock,
        )
        controller.start(duration_s=10.0)
        clock.advance(1.0)
        controller.pause()
        clock.advance(5.0)
        self.assertAlmostEqual(controller.elapsed_s, 1.0)
        self.assertAlmostEqual(metrics.snapshot().elapsed_s, 1.0)
        controller.resume()
        clock.advance(1.0)
        self.assertAlmostEqual(controller.elapsed_s, 2.0)
        self.assertAlmostEqual(metrics.snapshot().elapsed_s, 2.0)


if __name__ == "__main__":
    unittest.main()
