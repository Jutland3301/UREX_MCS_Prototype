#include "service.hpp"
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>

using namespace urex_pi;
static volatile std::sig_atomic_t running=1;
static void stop(int) { running=0; }
class MockBackend : public Backend {
    struct Pending { std::string id,payload; std::chrono::steady_clock::time_point due; };
    std::vector<Pending> pending;
    std::vector<Reception> received;
public:
    std::string mode="success";
    pb::Status snapshot() override {
        pb::Status s; s.set_max_tx_payload_bytes(63); s.set_clock_synchronized(false);
        for (int i=1;i<=5;++i) {
            auto *c=s.add_components(); c->set_component(static_cast<pb::Component>(i));
            c->set_health(i<=2?pb::READY:pb::UNAVAILABLE); c->set_configuration_summary("C++ MOCK ONLY — no hardware");
        }
        return s;
    }
    void submit_transmit(const std::string &id,const std::string &payload) override {
        pending.push_back({id,payload,std::chrono::steady_clock::now()+std::chrono::milliseconds(50)});
        std::cout << "MOCK_TX " << id << " bytes=" << payload.size() << std::endl;
    }
    std::vector<Completion> drain_completions() override {
        std::vector<Completion> result;
        for (auto it=pending.begin();it!=pending.end();) {
            if (mode=="timeout" || std::chrono::steady_clock::now()<it->due) { ++it; continue; }
            auto timestamp=unix_ms(); bool success=mode=="success";
            result.push_back({it->id,success,timestamp,success?"":"TX_FAILED",success?"":"Synthetic failure"});
            if (success) received.push_back({it->payload,timestamp,-54.0f,11.0f,true});
            it=pending.erase(it);
        }
        return result;
    }
    std::vector<Reception> drain_received() override { auto out=std::move(received); received.clear(); return out; }
};
int main(int argc,char **argv) {
    std::string endpoint="tcp://127.0.0.1:5557";
    MockBackend backend;
    for(int i=1;i<argc;++i) {
        std::string argument=argv[i];
        if (argument=="--connect" && i+1<argc) endpoint=argv[++i];
        else if (argument=="--mode" && i+1<argc) backend.mode=argv[++i];
        else { std::cerr << "Usage: mock_pi_cpp [--connect tcp://MCS:5557] [--mode success|fail|timeout]\n"; return 2; }
    }
    if (backend.mode!="success" && backend.mode!="fail" && backend.mode!="timeout") return 2;
    std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
    try {
        Service service(endpoint,backend);
        while(running) { service.tick(); std::this_thread::sleep_for(std::chrono::milliseconds(10)); }
    } catch(const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
