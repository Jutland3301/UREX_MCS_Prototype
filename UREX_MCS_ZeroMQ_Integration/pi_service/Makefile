CXX ?= g++
PROTOC ?= protoc
CPPFLAGS += -Ibuild -I. $(shell pkg-config --cflags protobuf libzmq)
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -pthread
LDLIBS += $(shell pkg-config --libs protobuf libzmq)

all: build/mock_pi_cpp

build/integration.pb.cc build/integration.pb.h &: ../schema/integration.proto
	mkdir -p build
	$(PROTOC) -I../schema --cpp_out=build ../schema/integration.proto

build/mock_pi_cpp: service.cpp service.hpp backend.hpp mock_main.cpp build/integration.pb.cc build/integration.pb.h
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) service.cpp mock_main.cpp build/integration.pb.cc $(LDLIBS) -o $@

clean:
	rm -rf build

.PHONY: all clean
