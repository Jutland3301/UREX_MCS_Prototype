#pragma once
#include "backend.hpp"
#include <memory>

namespace urex_pi {
// This service owns its DEALER socket. Construct, tick and destroy on one thread.
class Service {
public:
    Service(std::string endpoint, Backend &backend);
    ~Service();
    Service(const Service &) = delete;
    Service &operator=(const Service &) = delete;
    void tick();
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
uint64_t unix_ms();
}
