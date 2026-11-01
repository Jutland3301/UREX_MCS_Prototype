#include "service.hpp"
#include <zmq.h>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <random>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace urex_pi {
using Clock = std::chrono::steady_clock;
uint64_t unix_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}
static std::string uuid() {
    std::random_device rng;
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (int i = 0; i < 16; ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10) out << '-';
        unsigned b = rng() & 255;
        if (i == 6) b = (b & 15) | 64;
        if (i == 8) b = (b & 63) | 128;
        out << std::setw(2) << b;
    }
    return out.str();
}
static bool valid_uuid(const std::string &s) {
    static const std::regex pattern("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
    return std::regex_match(s, pattern);
}
static uint16_t crc(const std::string &bytes) {
    uint16_t value = 0xffff;
    for (unsigned char b : bytes) {
        value ^= uint16_t(b) << 8;
        for (int i = 0; i < 8; ++i)
            value = value & 0x8000 ? (value << 1) ^ 0x1021 : value << 1;
    }
    return value;
}
static std::string frame(const pb::IntegrationPacket &p) {
    std::string body = p.SerializeAsString();
    if (body.empty() || body.size() > 65536) throw std::runtime_error("body exceeds 64 KiB");
    std::string bytes = "UX";
    bytes += char(1);
    uint32_t n = body.size();
    for (int shift = 24; shift >= 0; shift -= 8) bytes += char(n >> shift);
    bytes += body;
    uint16_t check = crc(bytes);
    bytes += char(check >> 8); bytes += char(check);
    return bytes;
}
static pb::IntegrationPacket decode(const std::string &bytes) {
    if (bytes.size() < 10 || bytes.substr(0, 2) != "UX" || uint8_t(bytes[2]) != 1)
        throw std::runtime_error("bad magic/version or truncated frame");
    uint32_t n = 0;
    for (int i = 3; i < 7; ++i) n = (n << 8) | uint8_t(bytes[i]);
    if (!n || n > 65536 || bytes.size() != n + 9) throw std::runtime_error("bad length");
    uint16_t check = (uint16_t(uint8_t(bytes[bytes.size()-2])) << 8) | uint8_t(bytes.back());
    if (crc(bytes.substr(0, bytes.size()-2)) != check) throw std::runtime_error("bad CRC");
    pb::IntegrationPacket p;
    if (!p.ParseFromArray(bytes.data()+7, n) || p.schema_version() != 1 || !p.sequence() ||
        !p.timestamp_unix_ms() || !valid_uuid(p.session_id()) || !p.has_transmit_request() ||
        !valid_uuid(p.transmit_request().command_id()) || p.transmit_request().payload().empty())
        throw std::runtime_error("invalid metadata, payload or direction");
    return p;
}
static void validate_status(const pb::Status &status) {
    unsigned mask = 0;
    if (status.components_size() != 5 || !status.max_tx_payload_bytes() || status.max_tx_payload_bytes() > 65536)
        throw std::runtime_error("invalid backend status/limit");
    for (const auto &c : status.components()) {
        if (c.component() < pb::PI || c.component() > pb::SPACECRAFT ||
            c.health() < pb::INITIALIZING || c.health() > pb::UNAVAILABLE || (mask & (1u << c.component())))
            throw std::runtime_error("invalid backend component state");
        mask |= 1u << c.component();
    }
}
struct Service::Impl {
    struct Cached { std::string payload; pb::CommandResult result; Clock::time_point updated; };
    Backend &backend;
    void *context = nullptr, *socket = nullptr;
    std::string session = uuid(), last_status;
    uint64_t sequence = 0;
    Clock::time_point status_time = Clock::time_point::min();
    std::unordered_map<std::string, Cached> cache;
    Impl(std::string endpoint, Backend &b) : backend(b) {
        context = zmq_ctx_new();
        if (!context) throw std::runtime_error("zmq context failed");
        socket = zmq_socket(context, ZMQ_DEALER);
        if (!socket) { zmq_ctx_term(context); throw std::runtime_error("zmq socket failed"); }
        int zero=0, one=1, hwm=1000, heartbeat=1000, timeout=3000, reconnect=250, reconnect_max=2000;
        int64_t max_size=65545;
        const char identity[]="urex-pi";
        auto option = [&](int key, const void *value, size_t size) {
            if (zmq_setsockopt(socket, key, value, size)) throw std::runtime_error(zmq_strerror(zmq_errno()));
        };
        try {
            option(ZMQ_LINGER,&zero,sizeof zero); option(ZMQ_IMMEDIATE,&one,sizeof one);
            option(ZMQ_SNDHWM,&hwm,sizeof hwm); option(ZMQ_RCVHWM,&hwm,sizeof hwm);
            option(ZMQ_HEARTBEAT_IVL,&heartbeat,sizeof heartbeat); option(ZMQ_HEARTBEAT_TIMEOUT,&timeout,sizeof timeout);
            option(ZMQ_RECONNECT_IVL,&reconnect,sizeof reconnect); option(ZMQ_RECONNECT_IVL_MAX,&reconnect_max,sizeof reconnect_max);
            option(ZMQ_MAXMSGSIZE,&max_size,sizeof max_size); option(ZMQ_IDENTITY,identity,sizeof(identity)-1);
            if (zmq_connect(socket, endpoint.c_str())) throw std::runtime_error(zmq_strerror(zmq_errno()));
        } catch (...) { zmq_close(socket); zmq_ctx_term(context); throw; }
    }
    ~Impl() { zmq_close(socket); zmq_ctx_term(context); }
    pb::IntegrationPacket envelope(uint64_t timestamp=0) {
        pb::IntegrationPacket p;
        p.set_schema_version(1); p.set_session_id(session); p.set_sequence(++sequence);
        p.set_timestamp_unix_ms(timestamp ? timestamp : unix_ms());
        return p;
    }
    void send(const pb::IntegrationPacket &p) {
        auto bytes = frame(p);
        if (zmq_send(socket, bytes.data(), bytes.size(), ZMQ_DONTWAIT) < 0)
            std::cerr << "SEND_UNAVAILABLE: " << zmq_strerror(zmq_errno()) << '\n';
    }
    void result(const pb::CommandResult &r, uint64_t timestamp=0) {
        auto p = envelope(timestamp); *p.mutable_command_result() = r; send(p);
    }
    void finish(const std::string &id, pb::CommandState state, std::string code="", std::string message="", uint64_t timestamp=0) {
        auto &cached = cache.at(id);
        cached.result.set_command_id(id); cached.result.set_state(state);
        cached.result.set_error_code(code); cached.result.set_error_message(message);
        cached.updated = Clock::now(); result(cached.result, timestamp);
    }
    void reject(const std::string &id, std::string code, std::string message) {
        pb::CommandResult r; r.set_command_id(id); r.set_state(pb::REJECTED);
        r.set_error_code(code); r.set_error_message(message); result(r);
    }
    void receive(const std::string &bytes) {
        auto p = decode(bytes);
        const auto &r = p.transmit_request();
        auto found = cache.find(r.command_id());
        if (found != cache.end()) {
            if (found->second.payload != r.payload()) reject(r.command_id(),"ID_CONFLICT","same ID, different payload");
            else result(found->second.result);
            return;
        }
        if (cache.size() >= 4096) { reject(r.command_id(),"HARDWARE_BUSY","duplicate-protection cache full"); return; }
        auto status = backend.snapshot(); validate_status(status);
        cache.emplace(r.command_id(),Cached{r.payload(),{},Clock::now()});
        bool ready = false;
        for (const auto &c : status.components()) if (c.component() == pb::RADIO && c.health() == pb::READY) ready=true;
        if (r.payload().size() > status.max_tx_payload_bytes()) finish(r.command_id(),pb::REJECTED,"PAYLOAD_TOO_LARGE","hardware TX limit exceeded");
        else if (!ready) finish(r.command_id(),pb::REJECTED,"HARDWARE_NOT_READY","radio not READY");
        else {
            finish(r.command_id(),pb::ACCEPTED);
            try { backend.submit_transmit(r.command_id(),r.payload()); }
            catch (const std::exception &e) { finish(r.command_id(),pb::FAILED,"TX_FAILED",e.what()); }
        }
    }
    void tick() {
        for (int i=0; i<100; ++i) {
            zmq_msg_t message; zmq_msg_init(&message);
            int size = zmq_msg_recv(&message,socket,ZMQ_DONTWAIT);
            if (size < 0) { zmq_msg_close(&message); break; }
            std::string bytes(static_cast<const char *>(zmq_msg_data(&message)),size);
            bool more=zmq_msg_more(&message); zmq_msg_close(&message);
            if (more) {
                do { zmq_msg_init(&message); zmq_msg_recv(&message,socket,0); more=zmq_msg_more(&message); zmq_msg_close(&message); } while(more);
                std::cerr << "REJECTED_FRAME: multipart application body\n"; continue;
            }
            try { receive(bytes); } catch(const std::exception &e) { std::cerr << "REJECTED_FRAME: " << e.what() << '\n'; }
        }
        auto now=Clock::now(); auto status=backend.snapshot(); validate_status(status);
        auto encoded_status=status.SerializeAsString();
        if (last_status.empty() || now-status_time >= std::chrono::seconds(1) || encoded_status!=last_status) {
            auto p=envelope(); *p.mutable_status()=status; send(p);
            last_status=encoded_status; status_time=now;
        }
        for (const auto &e : backend.drain_completions()) {
            auto found=cache.find(e.command_id);
            if (found==cache.end() || found->second.result.state()!=pb::ACCEPTED) {
                std::cerr << "UNEXPECTED_COMPLETION\n"; continue;
            }
            if (!e.timestamp_ms) { std::cerr << "INVALID_COMPLETION_TIMESTAMP\n"; continue; }
            finish(e.command_id,e.success?pb::TX_COMPLETED:pb::FAILED,
                   e.success?"":(e.error_code.empty()?"TX_FAILED":e.error_code),e.success?"":e.error_message,e.timestamp_ms);
        }
        for (const auto &e : backend.drain_received()) {
            if (e.payload.empty() || !e.timestamp_ms || (e.radio_crc_ok && !*e.radio_crc_ok) ||
                (e.rssi_dbm && !std::isfinite(*e.rssi_dbm)) || (e.snr_db && !std::isfinite(*e.snr_db))) {
                std::cerr << "NATIVE_RX_REJECTED\n"; continue;
            }
            auto p=envelope(e.timestamp_ms); auto *rx=p.mutable_radio_receive(); rx->set_payload(e.payload);
            if (e.rssi_dbm) rx->set_rssi_dbm(*e.rssi_dbm);
            if (e.snr_db) rx->set_snr_db(*e.snr_db);
            if (e.radio_crc_ok) rx->set_radio_crc_ok(*e.radio_crc_ok);
            if (e.modem_config) {
                const auto &config = *e.modem_config;
                if ((config.has_frequency_hz() && (!config.frequency_hz() || config.frequency_hz()>9223372036854775807ULL)) ||
                    (config.has_spreading_factor() && !config.spreading_factor()) ||
                    (config.has_bandwidth_hz() && !config.bandwidth_hz())) {
                    std::cerr << "NATIVE_RX_REJECTED: invalid modem settings\n"; continue;
                }
                rx->mutable_modem_config()->CopyFrom(config);
            }
            try { send(p); } catch(const std::exception &error) { std::cerr << "NATIVE_RX_REJECTED: " << error.what() << '\n'; }
        }
        for (auto it=cache.begin(); it!=cache.end();) {
            if (it->second.result.state()!=pb::ACCEPTED && now-it->second.updated>std::chrono::minutes(10)) it=cache.erase(it);
            else ++it;
        }
    }
};
Service::Service(std::string endpoint, Backend &backend) : impl(std::make_unique<Impl>(endpoint,backend)) {}
Service::~Service()=default;
void Service::tick() { impl->tick(); }
}
