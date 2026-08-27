import random


class TelemetrySimulator:
    def __init__(self):
        self.packet_count = 0

    def generate(self):
        self.packet_count += 1

        return {
            "temperature": round(random.uniform(20.0, 35.0), 2),
            "voltage": round(random.uniform(4.8, 5.2), 2),
            "rssi": random.randint(-90, -50),
            "packet_count": self.packet_count,
        }
