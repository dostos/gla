#pragma once

#include "src/core/ipc/control_socket.h"
#include "src/core/ipc/shm_ring_buffer.h"
#include "src/core/store/frame_store.h"

#include <atomic>
#include <memory>
#include <string>
#include <vector>

namespace gla {

class Engine {
public:
    Engine(const std::string& socket_path, const std::string& shm_name,
           uint32_t shm_slots = 4, size_t slot_size = 64 * 1024 * 1024);
    ~Engine();

    // Start the engine main loop (blocking). Call from a thread.
    void run();

    // Signal the engine to stop
    void stop();

    // Access the frame store (for query engine)
    store::FrameStore& frame_store();
    const store::FrameStore& frame_store() const;

    // Control commands (called from query API)
    void request_pause();
    void request_resume();
    void request_step(uint32_t count);

    // Status
    bool is_running() const;
    bool is_paused() const;

private:
    void accept_connections();
    void process_client_messages(int client_fd);
    void handle_frame_ready(int client_fd, uint64_t frame_id, uint32_t slot_index);
    void ingest_frame(const void* shm_data, uint64_t data_size,
                      uint64_t frame_id);
    void send_control_to_clients();

    std::unique_ptr<ShmRingBuffer> shm_;
    std::unique_ptr<ipc::ControlSocketServer> socket_;
    store::FrameStore store_;

    std::atomic<bool> running_{false};
    std::atomic<bool> paused_{false};
    std::atomic<bool> paused_prev_{false};   // tracks last-sent state
    std::atomic<uint32_t> step_count_{0};

    std::vector<int> client_fds_;
    std::string socket_path_;
    std::string shm_name_;
    std::atomic<uint64_t> next_frame_id_{1};  // monotonic engine-assigned frame ID
};

} // namespace gla
