#include "src/core/ipc/control_socket.h"

#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>

namespace gla::ipc {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Write exactly len bytes; handles EINTR and partial writes.
static bool write_all(int fd, const void* buf, size_t len) {
    const uint8_t* p = static_cast<const uint8_t*>(buf);
    size_t remaining = len;
    while (remaining > 0) {
        ssize_t n = ::write(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;
        p += n;
        remaining -= static_cast<size_t>(n);
    }
    return true;
}

// Read exactly len bytes; handles EINTR and partial reads.
// Returns false on error or EOF.
static bool read_all(int fd, void* buf, size_t len) {
    uint8_t* p = static_cast<uint8_t*>(buf);
    size_t remaining = len;
    while (remaining > 0) {
        ssize_t n = ::read(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;  // EOF
        p += n;
        remaining -= static_cast<size_t>(n);
    }
    return true;
}

// Try a single non-blocking peek at the fd: if data available, read it all.
// Returns false if EAGAIN/EWOULDBLOCK (nothing available) or error.
static bool try_read_all(int fd, void* buf, size_t len) {
    uint8_t* p = static_cast<uint8_t*>(buf);
    size_t remaining = len;
    bool started = false;
    while (remaining > 0) {
        ssize_t n = ::read(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR) continue;
            if ((errno == EAGAIN || errno == EWOULDBLOCK) && !started) return false;
            // Partial: socket is non-blocking but data should be available once started
            return false;
        }
        if (n == 0) return false;  // EOF
        started = true;
        p += n;
        remaining -= static_cast<size_t>(n);
    }
    return true;
}

// Build and send a framed message: [4-byte big-endian length][1-byte type][payload]
// length = 1 (type) + payload bytes
static bool send_framed(int fd, MsgType type, const void* payload, size_t payload_len) {
    uint32_t length = static_cast<uint32_t>(1 + payload_len);
    uint32_t length_be = htonl(length);

    if (!write_all(fd, &length_be, 4)) return false;
    uint8_t type_byte = static_cast<uint8_t>(type);
    if (!write_all(fd, &type_byte, 1)) return false;
    if (payload_len > 0) {
        if (!write_all(fd, payload, payload_len)) return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// ControlSocketServer
// ---------------------------------------------------------------------------

ControlSocketServer::ControlSocketServer(const std::string& socket_path)
    : socket_path_(socket_path), server_fd_(-1) {
    // Remove stale socket file
    ::unlink(socket_path_.c_str());

    server_fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd_ < 0) return;

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

    if (::bind(server_fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(server_fd_);
        server_fd_ = -1;
        return;
    }

    if (::listen(server_fd_, 8) < 0) {
        ::close(server_fd_);
        server_fd_ = -1;
        return;
    }

    // Make accept non-blocking
    int flags = ::fcntl(server_fd_, F_GETFL, 0);
    ::fcntl(server_fd_, F_SETFL, flags | O_NONBLOCK);
}

ControlSocketServer::~ControlSocketServer() {
    if (server_fd_ >= 0) {
        ::close(server_fd_);
        server_fd_ = -1;
    }
    ::unlink(socket_path_.c_str());
}

int ControlSocketServer::accept_client() {
    struct sockaddr_un addr{};
    socklen_t addrlen = sizeof(addr);
    int cfd = ::accept(server_fd_,
                       reinterpret_cast<struct sockaddr*>(&addr),
                       &addrlen);
    if (cfd < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) return -1;
        return -1;
    }
    // Make client fd non-blocking for read_message
    int flags = ::fcntl(cfd, F_GETFL, 0);
    ::fcntl(cfd, F_SETFL, flags | O_NONBLOCK);
    return cfd;
}

bool ControlSocketServer::read_message(int client_fd,
                                       MsgType& type,
                                       std::vector<uint8_t>& payload) {
    uint32_t length_be = 0;
    if (!try_read_all(client_fd, &length_be, 4)) return false;

    uint32_t length = ntohl(length_be);
    if (length < 1) return false;

    // After getting the length header, read the rest (type + payload) blocking
    // by temporarily making it blocking for the rest of this call.
    // Actually, keep non-blocking but use read_all which retries EINTR.
    // Since we already got 4 bytes, the rest should follow quickly.
    // For simplicity switch to blocking mode for the body read.
    int flags = ::fcntl(client_fd, F_GETFL, 0);
    ::fcntl(client_fd, F_SETFL, flags & ~O_NONBLOCK);

    uint8_t type_byte = 0;
    if (!read_all(client_fd, &type_byte, 1)) {
        ::fcntl(client_fd, F_SETFL, flags);
        return false;
    }
    type = static_cast<MsgType>(type_byte);

    size_t payload_len = length - 1;
    payload.resize(payload_len);
    if (payload_len > 0) {
        if (!read_all(client_fd, payload.data(), payload_len)) {
            ::fcntl(client_fd, F_SETFL, flags);
            return false;
        }
    }

    ::fcntl(client_fd, F_SETFL, flags);
    return true;
}

bool ControlSocketServer::send_message(int client_fd,
                                       MsgType type,
                                       const void* payload,
                                       size_t len) {
    return send_framed(client_fd, type, payload, len);
}

// ---------------------------------------------------------------------------
// ControlSocketClient
// ---------------------------------------------------------------------------

bool ControlSocketClient::connect(const std::string& socket_path) {
    if (client_fd_ >= 0) {
        ::close(client_fd_);
        client_fd_ = -1;
    }

    client_fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (client_fd_ < 0) return false;

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path.c_str(), sizeof(addr.sun_path) - 1);

    if (::connect(client_fd_,
                  reinterpret_cast<struct sockaddr*>(&addr),
                  sizeof(addr)) < 0) {
        ::close(client_fd_);
        client_fd_ = -1;
        return false;
    }
    return true;
}

bool ControlSocketClient::send_handshake(uint32_t api_type, uint32_t pid) {
    HandshakePayload p{};
    p.protocol_version = htonl(PROTOCOL_VERSION);
    p.api_type         = htonl(api_type);
    p.pid              = htonl(pid);
    return send_message(MsgType::MSG_HANDSHAKE, &p, sizeof(p));
}

bool ControlSocketClient::wait_handshake_response() {
    MsgType type{};
    std::vector<uint8_t> payload;
    if (!read_message_blocking(type, payload)) return false;
    return type == MsgType::MSG_HANDSHAKE_OK;
}

bool ControlSocketClient::send_frame_ready(uint64_t frame_id, uint32_t slot_index) {
    FrameReadyPayload p{};
    // Store as big-endian
    uint32_t hi = static_cast<uint32_t>(frame_id >> 32);
    uint32_t lo = static_cast<uint32_t>(frame_id & 0xFFFFFFFF);
    uint32_t hi_be = htonl(hi);
    uint32_t lo_be = htonl(lo);
    std::memcpy(&p.frame_id, &hi_be, 4);
    std::memcpy(reinterpret_cast<uint8_t*>(&p.frame_id) + 4, &lo_be, 4);
    p.shm_slot_index = htonl(slot_index);
    return send_message(MsgType::MSG_FRAME_READY, &p, sizeof(p));
}

bool ControlSocketClient::read_control(ControlPayload& out) {
    // Make non-blocking temporarily
    int flags = ::fcntl(client_fd_, F_GETFL, 0);
    ::fcntl(client_fd_, F_SETFL, flags | O_NONBLOCK);

    MsgType type{};
    std::vector<uint8_t> payload;
    bool ok = read_message_nonblocking(type, payload);

    ::fcntl(client_fd_, F_SETFL, flags);

    if (!ok || type != MsgType::MSG_CONTROL) return false;
    if (payload.size() < sizeof(ControlPayload)) return false;

    std::memcpy(&out, payload.data(), sizeof(ControlPayload));
    // Deserialize step_frames from network byte order
    out.step_frames = ntohl(out.step_frames);
    return true;
}

void ControlSocketClient::close() {
    if (client_fd_ >= 0) {
        ::close(client_fd_);
        client_fd_ = -1;
    }
}

bool ControlSocketClient::send_message(MsgType type, const void* payload, size_t len) {
    if (client_fd_ < 0) return false;
    return send_framed(client_fd_, type, payload, len);
}

bool ControlSocketClient::read_message_blocking(MsgType& type,
                                                 std::vector<uint8_t>& payload) {
    if (client_fd_ < 0) return false;

    uint32_t length_be = 0;
    if (!read_all(client_fd_, &length_be, 4)) return false;

    uint32_t length = ntohl(length_be);
    if (length < 1) return false;

    uint8_t type_byte = 0;
    if (!read_all(client_fd_, &type_byte, 1)) return false;
    type = static_cast<MsgType>(type_byte);

    size_t payload_len = length - 1;
    payload.resize(payload_len);
    if (payload_len > 0) {
        if (!read_all(client_fd_, payload.data(), payload_len)) return false;
    }
    return true;
}

bool ControlSocketClient::read_message_nonblocking(MsgType& type,
                                                    std::vector<uint8_t>& payload) {
    if (client_fd_ < 0) return false;

    uint32_t length_be = 0;
    if (!try_read_all(client_fd_, &length_be, 4)) return false;

    uint32_t length = ntohl(length_be);
    if (length < 1) return false;

    // Switch to blocking for body once we have the header
    int flags = ::fcntl(client_fd_, F_GETFL, 0);
    ::fcntl(client_fd_, F_SETFL, flags & ~O_NONBLOCK);

    uint8_t type_byte = 0;
    if (!read_all(client_fd_, &type_byte, 1)) {
        ::fcntl(client_fd_, F_SETFL, flags);
        return false;
    }
    type = static_cast<MsgType>(type_byte);

    size_t payload_len = length - 1;
    payload.resize(payload_len);
    if (payload_len > 0) {
        if (!read_all(client_fd_, payload.data(), payload_len)) {
            ::fcntl(client_fd_, F_SETFL, flags);
            return false;
        }
    }

    ::fcntl(client_fd_, F_SETFL, flags);
    return true;
}

} // namespace gla::ipc
