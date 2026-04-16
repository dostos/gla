#include "src/core/engine.h"

#include "src/core/ipc/protocol.h"
#include "src/core/store/raw_frame.h"

#include <arpa/inet.h>
#include <poll.h>
#include <unistd.h>

#include <chrono>
#include <cstring>
#include <ctime>
#include <vector>

namespace gla {

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------

Engine::Engine(const std::string& socket_path, const std::string& shm_name,
               uint32_t shm_slots, size_t slot_size)
    : socket_path_(socket_path), shm_name_(shm_name) {
    shm_   = ShmRingBuffer::create(shm_name, shm_slots, slot_size);
    socket_ = std::make_unique<ipc::ControlSocketServer>(socket_path);
}

Engine::~Engine() {
    stop();
    for (int fd : client_fds_) {
        if (fd >= 0) ::close(fd);
    }
}

// ---------------------------------------------------------------------------
// Control
// ---------------------------------------------------------------------------

void Engine::stop() {
    running_.store(false, std::memory_order_relaxed);
}

void Engine::request_pause() {
    paused_.store(true, std::memory_order_relaxed);
}

void Engine::request_resume() {
    paused_.store(false, std::memory_order_relaxed);
}

void Engine::request_step(uint32_t count) {
    step_count_.fetch_add(count, std::memory_order_relaxed);
}

bool Engine::is_running() const {
    return running_.load(std::memory_order_relaxed);
}

bool Engine::is_paused() const {
    return paused_.load(std::memory_order_relaxed);
}

store::FrameStore& Engine::frame_store() {
    return store_;
}

const store::FrameStore& Engine::frame_store() const {
    return store_;
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

void Engine::run() {
    running_.store(true, std::memory_order_relaxed);

    while (running_.load(std::memory_order_relaxed)) {
        // Build pollfd array: server socket + all client fds
        std::vector<struct pollfd> pfds;
        pfds.reserve(1 + client_fds_.size());

        struct pollfd server_pfd{};
        server_pfd.fd     = socket_->fd();
        server_pfd.events = POLLIN;
        pfds.push_back(server_pfd);

        for (int fd : client_fds_) {
            struct pollfd pfd{};
            pfd.fd     = fd;
            pfd.events = POLLIN;
            pfds.push_back(pfd);
        }

        int ret = ::poll(pfds.data(), static_cast<nfds_t>(pfds.size()), 100 /*ms*/);

        if (ret < 0) {
            if (errno == EINTR) continue;
            break; // unexpected error — stop loop
        }

        // Check server socket for new connections
        if (pfds[0].revents & POLLIN) {
            accept_connections();
        }

        // Check client fds — iterate backwards so we can erase cleanly
        for (int i = static_cast<int>(client_fds_.size()) - 1; i >= 0; --i) {
            auto& pfd = pfds[1 + i];
            if (pfd.revents & (POLLIN | POLLHUP | POLLERR)) {
                process_client_messages(client_fds_[i]);
                // If the fd was closed/erased, remove it
                if (client_fds_[i] < 0) {
                    client_fds_.erase(client_fds_.begin() + i);
                }
            }
        }

        // Drain SHM slots that were written directly by a shim
        // (these arrive independently of FRAME_READY in direct-shm mode)
        {
            ShmRingBuffer::ReadSlot slot;
            while ((slot = shm_->claim_read_slot()).data != nullptr) {
                ingest_frame(slot.data, slot.size, /*frame_id=*/0);
                shm_->release_read(slot.index);
            }
        }

        // Send pending control commands to shim clients
        send_control_to_clients();
    }
}

// ---------------------------------------------------------------------------
// accept_connections
// ---------------------------------------------------------------------------

void Engine::accept_connections() {
    int cfd = socket_->accept_client();
    if (cfd < 0) return;

    // Read handshake
    ipc::MsgType type{};
    std::vector<uint8_t> payload;
    if (!socket_->read_message(cfd, type, payload) ||
        type != ipc::MsgType::MSG_HANDSHAKE ||
        payload.size() < sizeof(ipc::HandshakePayload)) {
        socket_->send_message(cfd, ipc::MsgType::MSG_HANDSHAKE_FAIL, nullptr, 0);
        ::close(cfd);
        return;
    }

    ipc::HandshakePayload hs{};
    std::memcpy(&hs, payload.data(), sizeof(hs));
    uint32_t version = ntohl(hs.protocol_version);

    if (version != ipc::PROTOCOL_VERSION) {
        socket_->send_message(cfd, ipc::MsgType::MSG_HANDSHAKE_FAIL, nullptr, 0);
        ::close(cfd);
        return;
    }

    socket_->send_message(cfd, ipc::MsgType::MSG_HANDSHAKE_OK, nullptr, 0);
    client_fds_.push_back(cfd);
}

// ---------------------------------------------------------------------------
// process_client_messages — read any pending messages from one client
// ---------------------------------------------------------------------------

void Engine::process_client_messages(int client_fd) {
    ipc::MsgType type{};
    std::vector<uint8_t> payload;

    // Read all available messages from this fd (non-blocking)
    while (socket_->read_message(client_fd, type, payload)) {
        if (type == ipc::MsgType::MSG_FRAME_READY &&
            payload.size() >= sizeof(ipc::FrameReadyPayload)) {
            ipc::FrameReadyPayload fr{};
            std::memcpy(&fr, payload.data(), sizeof(fr));

            // Decode big-endian fields
            uint32_t hi, lo;
            std::memcpy(&hi, &fr.frame_id, 4);
            std::memcpy(&lo, reinterpret_cast<const uint8_t*>(&fr.frame_id) + 4, 4);
            uint64_t frame_id = (static_cast<uint64_t>(ntohl(hi)) << 32) | ntohl(lo);
            uint32_t slot_index = ntohl(fr.shm_slot_index);

            handle_frame_ready(client_fd, frame_id, slot_index);
        }
        // Ignore other message types from client for now
    }

    // Check if connection was closed (read_message would have returned false
    // on EOF; detect by trying a peek)
    char buf;
    ssize_t n = ::recv(client_fd, &buf, 1, MSG_PEEK | MSG_DONTWAIT);
    if (n == 0) {
        // EOF — client disconnected
        ::close(client_fd);
        // Mark fd as -1; caller will erase it
        for (int& fd : client_fds_) {
            if (fd == client_fd) {
                fd = -1;
                break;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// handle_frame_ready — client told us a slot is ready; read it from shm
// ---------------------------------------------------------------------------

void Engine::handle_frame_ready(int /*client_fd*/, uint64_t frame_id,
                                  uint32_t slot_index) {
    // We don't use claim_read_slot() here since the slot was nominated by the
    // shim via FRAME_READY.  Instead we access the slot directly and transition
    // its state from READY → READING → FREE manually.
    if (!shm_) return;

    uint32_t num = shm_->num_slots();
    if (slot_index >= num) return;

    // Use the public API: claim_read_slot scans from next_read_ and will pick
    // up the nominated slot if it is in READY state.  However, to honour the
    // specific slot index we may need to iterate.  For simplicity (and since
    // in practice the shim only has one outstanding slot), we call
    // claim_read_slot() in a short retry loop.
    ShmRingBuffer::ReadSlot slot{nullptr, 0, 0};
    for (int attempt = 0; attempt < static_cast<int>(num) && slot.data == nullptr; ++attempt) {
        slot = shm_->claim_read_slot();
        if (slot.data != nullptr && slot.index != slot_index) {
            // Wrong slot — process it anyway to avoid stalling the ring buffer
            ingest_frame(slot.data, slot.size, 0);
            shm_->release_read(slot.index);
            slot = {nullptr, 0, 0};
        }
    }

    if (slot.data == nullptr) return;

    ingest_frame(slot.data, slot.size, frame_id);
    shm_->release_read(slot.index);
}

// ---------------------------------------------------------------------------
// ingest_frame — copy shm data into a RawFrame and store it
// ---------------------------------------------------------------------------

void Engine::ingest_frame(const void* shm_data, uint64_t data_size,
                           uint64_t frame_id) {
    store::RawFrame frame{};
    frame.frame_id  = frame_id;
    frame.api_type  = 0; // GL (TODO: carry api_type from handshake)

    // Record a monotonic timestamp
    struct timespec ts{};
    ::clock_gettime(CLOCK_MONOTONIC, &ts);
    frame.timestamp = static_cast<double>(ts.tv_sec) +
                      static_cast<double>(ts.tv_nsec) * 1e-9;

    // Store raw bulk data as fb_color for now.
    // Full FlatBuffer draw-call deserialization is a TODO.
    if (shm_data && data_size > 0) {
        const auto* bytes = static_cast<const uint8_t*>(shm_data);
        frame.fb_color.assign(bytes, bytes + data_size);
    }

    store_.store(std::move(frame));
}

// ---------------------------------------------------------------------------
// send_control_to_clients
// ---------------------------------------------------------------------------

void Engine::send_control_to_clients() {
    bool cur_paused   = paused_.load(std::memory_order_relaxed);
    bool prev_paused  = paused_prev_.load(std::memory_order_relaxed);
    uint32_t steps    = step_count_.exchange(0, std::memory_order_relaxed);

    bool state_changed = (cur_paused != prev_paused) || (steps > 0);
    if (!state_changed) return;

    paused_prev_.store(cur_paused, std::memory_order_relaxed);

    ipc::ControlPayload ctrl{};
    ctrl.pause       = cur_paused ? 1 : 0;
    ctrl.resume      = (!cur_paused && prev_paused) ? 1 : 0;
    ctrl.step_frames = htonl(steps);

    for (int fd : client_fds_) {
        if (fd >= 0) {
            socket_->send_message(fd, ipc::MsgType::MSG_CONTROL, &ctrl, sizeof(ctrl));
        }
    }
}

} // namespace gla
