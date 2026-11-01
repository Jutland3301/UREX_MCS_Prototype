# Modem settings captured at reception

`RadioReceive.modem_config` is an additive Protobuf field. The UX framing, CRC,
existing field numbers, and schema version 1 remain unchanged. Old Pi messages
without this field are still accepted. Python bindings are committed and ready
to use. C++ services must regenerate their local bindings and rebuild:

```sh
make -C pi_service clean
make -C pi_service
```

A custom native service should rebuild its own target against the updated
`schema/integration.proto`; `pi_service`'s Makefile only builds the mock executable.

## Hardware adapter requirement

Capture the active frequency/modulation/settings **inside the RX callback or
under the same settings lock used for reception**, together with the RX timestamp,
payload, RSSI and SNR. Copy that snapshot into the received-event queue. Do not
query the current modem settings later when draining that queue, because the
radio may have been reconfigured between those two moments.

The values below are variable names from the hardware adapter, not fabricated
defaults. Include only actual available measurements/settings. No value is inferred
from RSSI, SNR or the Status summary. SF may be absent for modulation modes that
do not use LoRa spreading factor.

Python adapter example:

```python
settings = pb.ModemConfiguration(
    frequency_hz=actual_frequency_hz,
    modulation=actual_modulation,
    radio_id=actual_radio_id,
)
if actual_sf is not None:
    settings.spreading_factor = actual_sf
if actual_bandwidth_hz is not None:
    settings.bandwidth_hz = actual_bandwidth_hz
if actual_coding_rate is not None:
    settings.coding_rate = actual_coding_rate

rx_queue.append(Reception(
    payload=received_bytes,
    timestamp_ms=rx_timestamp_ms,
    rssi_dbm=measured_rssi,
    snr_db=measured_snr,
    radio_crc_ok=crc_ok,
    modem_config=settings,
))
```

`Reception` copies the Protobuf settings object on construction, so changing the
original object later cannot mutate a previously queued RX event. The native
adapter still needs to make the initial settings capture atomic with reception.

C++ adapter example (inside the same RX/settings lock):

```cpp
urex_pi::Reception event;
event.payload = received_bytes;
event.timestamp_ms = rx_timestamp_ms;
event.rssi_dbm = measured_rssi;
event.snr_db = measured_snr;
event.radio_crc_ok = crc_ok;
urex_pi::pb::ModemConfiguration settings;
settings.set_frequency_hz(actual_frequency_hz);
settings.set_modulation(actual_modulation);
settings.set_radio_id(actual_radio_id);
// Populate SF/bandwidth/coding rate only when available for this radio mode.
event.modem_config = settings; // Value copy into the event.
rx_queue.push_back(std::move(event));
```

The Python PiEngine and C++ Service forward these values from the event. The
radio hardware driver remains the hardware team's existing implementation; it is
not replaced with a mock or an invented register-reading API.

## MCS storage and compatibility

SQLite/JSONL preserve the event timestamp, payload, RSSI/SNR and these new columns:

- `modem_frequency_hz`, `modem_spreading_factor`, `modem_bandwidth_hz`
- `modem_coding_rate`, `modem_modulation`, `modem_radio_id`
- `modem_config_source`, plus a readable `modem_config_summary`

`rx_event` means only the fields supplied in that event are present; it does not
mean every possible modem setting was measured. `rx_event_empty` explicitly means
a config message arrived with no known values. `last_status_summary` is a fallback
from a preceding Status, tagged with that Status time/sequence and kept out of
the typed per-event columns. `unavailable` means no usable configuration source.
Unknown values become NULL in SQLite. Existing DBs remain unchanged; each run
creates a new DB with the current schema.

GUI Received payloads includes the configuration and source columns. Downstream
analysis should use only `rx_event` rows for per-event configuration claims.
Numeric fields, when reported, must be positive and fit SQLite's signed integer
range. Old peers remain usable, but cannot provide the new evidence until their
hardware adapter populates the added field.
