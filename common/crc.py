"""
Temporary CRC implementation.

The system definition leaves the final CRC algorithm TBD. CRC-16-CCITT-FALSE
is implemented here only as a working prototype so simulator/parser tests can
be written. Replace this function if/when the team selects another CRC.
"""

CRC16_CCITT_POLY = 0x1021
CRC16_CCITT_INIT = 0xFFFF


def calculate_crc16_ccitt(data: bytes) -> int:
    crc = CRC16_CCITT_INIT

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC16_CCITT_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


def verify_crc16_ccitt(data: bytes, expected_crc: int) -> bool:
    return calculate_crc16_ccitt(data) == expected_crc
