#pragma once
#include "integration.pb.h"
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace urex_pi {
namespace pb = urex::integration::v1;
struct Completion {
    std::string command_id;
    bool success;
    uint64_t timestamp_ms;
    std::string error_code, error_message;
};
struct Reception {
    std::string payload;  // Binary bytes, not a NUL-terminated C string.
    uint64_t timestamp_ms;
    std::optional<float> rssi_dbm, snr_db;
    std::optional<bool> radio_crc_ok;
};
class Backend {
public:
    virtual ~Backend() = default;
    virtual pb::Status snapshot() = 0;
    // Enqueue to the TX worker without blocking this networking loop.
    virtual void submit_transmit(const std::string &id, const std::string &bytes) = 0;
    // Drain thread-safe queues filled by existing TX/RX workers.
    virtual std::vector<Completion> drain_completions() = 0;
    virtual std::vector<Reception> drain_received() = 0;
};
}
