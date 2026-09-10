from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from common.enums import CRCStatus, MessageType, ParseStatus, RadioState
from common.packet import Packet
from common.telemetry_state import TelemetryState
from packet.encoder import PacketEncoder
from packet.generated import urex_pb2
from packet.parser import PacketParser
from packet.profiles import CAN_STATUS, PROVISIONAL_PROFILE, RADIO_STATUS
from simulator.telemetry_simulator import TelemetrySimulator


class PacketPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.encoder = PacketEncoder(PROVISIONAL_PROFILE)
        self.parser = PacketParser(PROVISIONAL_PROFILE)

    @staticmethod
    def _radio_packet() -> Packet:
        return Packet(
            protocol_version=1,
            message_type=MessageType.TELEMETRY,
            source_id=2,
            destination_id=100,
            packet_id=RADIO_STATUS,
            sequence_number=7,
            timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc),
            payload={
                "state": RadioState.RX,
                "frequency_hz": 437_000_000,
                "rssi_dbm": -67.25,
                "snr_db": 12.5,
                "tx_power_dbm": 20.0,
                "bitrate_bps": 9_600,
                "channel_id": 1,
                "rx_packet_count": 123,
                "tx_packet_count": 4,
                "rx_error_count": 2,
                "packet_loss_count": 1,
                "pa_temperature_c": 42.5,
                "lock_status": True,
            },
        )

    @staticmethod
    def _protobuf_body(raw: bytes) -> bytes:
        start = PROVISIONAL_PROFILE.header_size
        end = len(raw) - PROVISIONAL_PROFILE.crc_size
        return raw[start:end]

    def test_protobuf_crc_radio_golden_vector(self) -> None:
        raw = self.encoder.encode(self._radio_packet())
        self.assertEqual(
            raw.hex(),
            "5558010000003f"
            "080110011802206430073880e8c2a48634"
            "8a202b080310c0aeb0d0011d008086c225000048412d0000a041"
            "30804b3801407b4804500258016500002a426801"
            "519a",
        )

        result = self.parser.parse(raw)
        self.assertTrue(result.ok, result.errors)
        assert result.packet is not None
        self.assertEqual(result.packet.meta.packet_id, RADIO_STATUS)
        self.assertEqual(result.packet.meta.total_length, 72)
        self.assertEqual(result.packet.meta.application_crc_status, CRCStatus.OK)
        self.assertAlmostEqual(result.packet.fields["rssi_dbm"], -67.25, places=4)
        self.assertAlmostEqual(result.packet.fields["snr_db"], 12.5, places=4)

    def test_packet_id_is_defined_once_by_protobuf_oneof_number(self) -> None:
        proto = urex_pb2.UrexPacket()
        proto.ParseFromString(self._protobuf_body(self.encoder.encode(self._radio_packet())))
        payload_name = proto.WhichOneof("payload")
        self.assertEqual(payload_name, "radio_status")
        self.assertEqual(proto.DESCRIPTOR.fields_by_name[payload_name].number, RADIO_STATUS)

    def test_crc_corruption_is_rejected_before_protobuf_decode(self) -> None:
        raw = bytearray(self.encoder.encode(self._radio_packet()))
        raw[PROVISIONAL_PROFILE.header_size + 5] ^= 0x01
        result = self.parser.parse(raw)
        self.assertEqual(result.status, ParseStatus.INVALID_CRC)
        self.assertEqual(result.application_crc_status, CRCStatus.FAIL)
        self.assertIsNone(result.packet)

    def test_declared_length_mismatch_is_rejected(self) -> None:
        raw = self.encoder.encode(self._radio_packet())[:-1]
        result = self.parser.parse(raw)
        self.assertEqual(result.status, ParseStatus.INVALID_LENGTH)

    def test_unknown_protocol_version_with_valid_crc_is_rejected(self) -> None:
        packet = self._radio_packet()
        packet.protocol_version = 0xFF
        raw = self.encoder.encode(packet)
        result = self.parser.parse(raw)
        self.assertEqual(result.status, ParseStatus.UNSUPPORTED_VERSION)
        self.assertEqual(result.application_crc_status, CRCStatus.OK)
        self.assertIsNone(result.packet)

    def test_optional_field_presence_replaces_numeric_sentinels(self) -> None:
        packet = self._radio_packet()
        packet.payload["frequency_hz"] = None
        packet.payload["lock_status"] = None
        raw = self.encoder.encode(packet)

        proto = urex_pb2.UrexPacket()
        proto.ParseFromString(self._protobuf_body(raw))
        self.assertFalse(proto.radio_status.HasField("frequency_hz"))
        self.assertFalse(proto.radio_status.HasField("lock_status"))

        result = self.parser.parse(raw)
        self.assertTrue(result.ok, result.errors)
        assert result.packet is not None
        self.assertIsNone(result.packet.fields["frequency_hz"])
        self.assertIsNone(result.packet.fields["lock_status"])

    def test_state_merges_partial_packets(self) -> None:
        simulator = TelemetrySimulator()
        messages = simulator.generate_messages(self.encoder)
        results = [self.parser.parse(message) for message in messages]
        by_id = {
            result.packet.meta.packet_id: result
            for result in results
            if result.packet is not None
        }
        state = TelemetryState(PROVISIONAL_PROFILE)
        state.apply(by_id[RADIO_STATUS])
        saved_rssi = state.frame.radio.rssi_dbm
        state.apply(by_id[CAN_STATUS])
        self.assertEqual(state.frame.radio.rssi_dbm, saved_rssi)
        self.assertGreaterEqual(state.frame.can.rx_frame_count, 0)

    def test_optional_terminator_is_profile_controlled(self) -> None:
        profile = replace(PROVISIONAL_PROFILE, terminator=b"\x00")
        raw = PacketEncoder(profile).encode(self._radio_packet())
        self.assertTrue(raw.endswith(b"\x00"))
        self.assertTrue(PacketParser(profile).parse(raw).ok)
        self.assertEqual(
            PacketParser(profile).parse(raw[:-1]).status,
            ParseStatus.INVALID_LENGTH,
        )

    def test_hardware_crc_is_mandatory_in_v03b(self) -> None:
        profile = replace(
            PROVISIONAL_PROFILE,
            crc=replace(PROVISIONAL_PROFILE.crc, enabled=False),
        )
        with self.assertRaisesRegex(ValueError, "requires application CRC"):
            PacketEncoder(profile).encode(self._radio_packet())

    def test_protobuf_removed_packet_level_byte_order_switch(self) -> None:
        self.assertFalse(hasattr(PROVISIONAL_PROFILE, "byte_order"))
        self.assertEqual(PROVISIONAL_PROFILE.frame.byte_order, "big")
        self.assertEqual(PROVISIONAL_PROFILE.crc.byte_order, "big")

    def test_64_bytes_is_not_assumed_as_mcs_limit(self) -> None:
        raw = self.encoder.encode(self._radio_packet())
        self.assertGreater(len(raw), 64)
        restrictive_profile = replace(PROVISIONAL_PROFILE, max_message_size=40)
        result = PacketParser(restrictive_profile).parse(raw)
        self.assertEqual(result.status, ParseStatus.TOO_LARGE)
        self.assertIsNone(PROVISIONAL_PROFILE.max_message_size)


class SimulatorFaultTests(unittest.TestCase):
    def test_crc_fault_enters_real_parser(self) -> None:
        encoder = PacketEncoder(PROVISIONAL_PROFILE)
        parser = PacketParser(PROVISIONAL_PROFILE)
        simulator = TelemetrySimulator()
        simulator.inject_crc_error()
        results = [parser.parse(raw) for raw in simulator.generate_messages(encoder)]
        self.assertEqual(results[0].status, ParseStatus.INVALID_CRC)
        self.assertTrue(all(result.ok for result in results[1:]))

    def test_parse_fault_enters_real_parser_with_valid_crc(self) -> None:
        encoder = PacketEncoder(PROVISIONAL_PROFILE)
        parser = PacketParser(PROVISIONAL_PROFILE)
        simulator = TelemetrySimulator()
        simulator.inject_parse_error()
        results = [parser.parse(raw) for raw in simulator.generate_messages(encoder)]
        self.assertEqual(results[0].status, ParseStatus.UNSUPPORTED_VERSION)
        self.assertEqual(results[0].application_crc_status, CRCStatus.OK)
        self.assertTrue(all(result.ok for result in results[1:]))


if __name__ == "__main__":
    unittest.main()
