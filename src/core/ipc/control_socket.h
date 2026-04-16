#pragma once

#include "src/core/ipc/protocol.h"
#include <string>
#include <vector>
#include <cstdint>

namespace gla::ipc {

// ---------------------------------------------------------------------------
// ControlSocketServer — engine side
// ---------------------------------------------------------------------------
class ControlSocketServer {
public:
    explicit ControlSocketServer(const std::string& socket_path);
    ~ControlSocketServer();

    // Non-blocking accept; returns client fd or -1 if none pending
    int accept_client();

    // Read one complete length-prefixed message from client_fd (non-blocking).
    // Returns false if no complete message is available or connection closed.
    bool read_message(int client_fd, MsgType& type, std::vector<uint8_t>& payload);

    // Write a length-prefixed message to client_fd.
    bool send_message(int client_fd, MsgType type, const void* payload, size_t len);

    // Server listening fd (use for poll/select)
    int fd() const { return server_fd_; }

private:
    std::string socket_path_;
    int server_fd_{-1};
};

// ---------------------------------------------------------------------------
// ControlSocketClient — shim side (implemented in core for testing)
// ---------------------------------------------------------------------------
class ControlSocketClient {
public:
    ControlSocketClient() = default;
    ~ControlSocketClient() { close(); }

    bool connect(const std::string& socket_path);

    // Send MSG_HANDSHAKE with PROTOCOL_VERSION
    bool send_handshake(uint32_t api_type, uint32_t pid);

    // Block until MSG_HANDSHAKE_OK or MSG_HANDSHAKE_FAIL is received.
    // Returns true if OK, false if FAIL or error.
    bool wait_handshake_response();

    // Send MSG_FRAME_READY
    bool send_frame_ready(uint64_t frame_id, uint32_t slot_index);

    // Non-blocking read of MSG_CONTROL; returns false if nothing available
    bool read_control(ControlPayload& out);

    void close();

    int fd() const { return client_fd_; }

private:
    // Send a length-prefixed message
    bool send_message(MsgType type, const void* payload, size_t len);

    // Read one complete length-prefixed message (blocking)
    bool read_message_blocking(MsgType& type, std::vector<uint8_t>& payload);

    // Read one complete length-prefixed message (non-blocking)
    bool read_message_nonblocking(MsgType& type, std::vector<uint8_t>& payload);

    int client_fd_{-1};
};

} // namespace gla::ipc
