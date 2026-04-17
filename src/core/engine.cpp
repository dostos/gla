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
            /* Shim sends FrameReadyPayload in native endian (not network order).
             * Read fields directly — no ntohl conversion. */
            uint64_t frame_id = fr.frame_id;
            uint32_t slot_index = fr.shm_slot_index;

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
    // Use engine-assigned monotonic ID to avoid collisions across shim connections
    frame.frame_id  = next_frame_id_.fetch_add(1);
    (void)frame_id;  // shim's frame_id ignored
    frame.api_type  = 0; // GL

    // Record a monotonic timestamp
    struct timespec ts{};
    ::clock_gettime(CLOCK_MONOTONIC, &ts);
    frame.timestamp = static_cast<double>(ts.tv_sec) +
                      static_cast<double>(ts.tv_nsec) * 1e-9;

    // Parse the shim's binary frame layout:
    //   [0..3]      width  (uint32_t, LE)
    //   [4..7]      height (uint32_t, LE)
    //   [8..]       color  (width * height * 4 bytes, RGBA8)
    //   [8+w*h*4..] depth  (width * height * 4 bytes, float32)
    //   [8+2*w*h*4..] draw call data:
    //       uint32  draw_call_count
    //       per draw call:
    //           uint32  id
    //           uint32  primitive_type
    //           uint32  vertex_count
    //           uint32  index_count
    //           uint32  instance_count
    //           uint32  shader_program_id
    //           int32[4] viewport
    //           int32[4] scissor
    //           uint8   scissor_enabled, depth_test, depth_write, _pad
    //           uint32  depth_func
    //           uint8   blend_enabled, _pad[3]
    //           uint32  blend_src
    //           uint32  blend_dst
    //           uint8   cull_enabled, _pad[3]
    //           uint32  cull_mode
    //           uint32  front_face
    //           uint32  texture_count
    //           texture_count * { uint32 slot, uint32 texture_id,
    //                             uint32 width, uint32 height, uint32 format }
    //           uint32  param_count
    //           param_count * { uint32 location, uint32 type, uint32 data_size, <data> }
    //
    // Minimum valid frame requires at least the 8-byte header.
    if (shm_data && data_size >= 8) {
        const auto* bytes = static_cast<const uint8_t*>(shm_data);

        uint32_t w, h;
        std::memcpy(&w, bytes + 0, 4);
        std::memcpy(&h, bytes + 4, 4);

        frame.fb_width  = w;
        frame.fb_height = h;

        const uint64_t color_bytes = static_cast<uint64_t>(w) * h * 4u;
        const uint64_t depth_bytes = static_cast<uint64_t>(w) * h * 4u;

        const uint8_t* color_ptr = bytes + 8;
        const uint8_t* depth_ptr = color_ptr + color_bytes;

        if (data_size >= 8 + color_bytes && w > 0 && h > 0) {
            frame.fb_color.assign(color_ptr, color_ptr + color_bytes);
        }

        if (data_size >= 8 + color_bytes + depth_bytes && w > 0 && h > 0) {
            const uint32_t pixel_count = w * h;
            frame.fb_depth.resize(pixel_count);
            std::memcpy(frame.fb_depth.data(), depth_ptr, depth_bytes);
        }

        // --- Draw call metadata ---
        const uint64_t pixel_section = 8 + color_bytes + depth_bytes;
        if (data_size > pixel_section + 4) {
            const uint8_t* dc_ptr = bytes + pixel_section;
            const uint8_t* dc_end = bytes + data_size;

            // Helper lambda: read T from dc_ptr and advance it
            auto read_u32 = [&](uint32_t& out) -> bool {
                if (dc_ptr + 4 > dc_end) return false;
                std::memcpy(&out, dc_ptr, 4);
                dc_ptr += 4;
                return true;
            };
            auto read_i32 = [&](int32_t& out) -> bool {
                if (dc_ptr + 4 > dc_end) return false;
                std::memcpy(&out, dc_ptr, 4);
                dc_ptr += 4;
                return true;
            };
            auto read_u8 = [&](uint8_t& out) -> bool {
                if (dc_ptr + 1 > dc_end) return false;
                out = *dc_ptr++;
                return true;
            };
            auto skip = [&](size_t n) -> bool {
                if (dc_ptr + n > dc_end) return false;
                dc_ptr += n;
                return true;
            };

            uint32_t dc_count = 0;
            if (!read_u32(dc_count)) goto done_dc;
            if (dc_count > 65536) dc_count = 0; // sanity cap

            frame.draw_calls.reserve(dc_count);

            for (uint32_t i = 0; i < dc_count; ++i) {
                store::RawDrawCall dc{};

                uint32_t id, prim, vc, ic, inst, prog;
                if (!read_u32(id))   break;
                if (!read_u32(prim)) break;
                if (!read_u32(vc))   break;
                if (!read_u32(ic))   break;
                if (!read_u32(inst)) break;
                if (!read_u32(prog)) break;

                dc.id               = id;
                dc.primitive_type   = prim;
                dc.vertex_count     = vc;
                dc.index_count      = ic;
                dc.instance_count   = inst;
                dc.shader_program_id = prog;

                // viewport[4]
                for (int k = 0; k < 4; ++k) {
                    if (!read_i32(dc.pipeline.viewport[k])) goto done_dc;
                }
                // scissor[4]
                for (int k = 0; k < 4; ++k) {
                    if (!read_i32(dc.pipeline.scissor[k])) goto done_dc;
                }

                // booleans + pad
                uint8_t b0, b1, b2, pad;
                if (!read_u8(b0)) goto done_dc;
                if (!read_u8(b1)) goto done_dc;
                if (!read_u8(b2)) goto done_dc;
                if (!read_u8(pad)) goto done_dc;
                dc.pipeline.scissor_enabled = (b0 != 0);
                dc.pipeline.depth_test      = (b1 != 0);
                dc.pipeline.depth_write     = (b2 != 0);

                uint32_t depth_func;
                if (!read_u32(depth_func)) goto done_dc;
                dc.pipeline.depth_func = depth_func;

                // blend
                uint8_t blend_en;
                if (!read_u8(blend_en)) goto done_dc;
                if (!skip(3)) goto done_dc; // pad
                dc.pipeline.blend_enabled = (blend_en != 0);
                if (!read_u32(dc.pipeline.blend_src)) goto done_dc;
                if (!read_u32(dc.pipeline.blend_dst)) goto done_dc;

                // cull
                uint8_t cull_en;
                if (!read_u8(cull_en)) goto done_dc;
                if (!skip(3)) goto done_dc; // pad
                dc.pipeline.cull_enabled = (cull_en != 0);
                if (!read_u32(dc.pipeline.cull_mode))  goto done_dc;
                if (!read_u32(dc.pipeline.front_face)) goto done_dc;

                // textures
                uint32_t tex_count;
                if (!read_u32(tex_count)) goto done_dc;
                if (tex_count > 32) tex_count = 32; // sanity
                dc.textures.reserve(tex_count);
                for (uint32_t t = 0; t < tex_count; ++t) {
                    store::RawDrawCall::Texture tex{};
                    if (!read_u32(tex.slot))       goto done_dc;
                    if (!read_u32(tex.texture_id)) goto done_dc;
                    if (!read_u32(tex.width))      goto done_dc;
                    if (!read_u32(tex.height))     goto done_dc;
                    if (!read_u32(tex.format))     goto done_dc;
                    dc.textures.push_back(std::move(tex));
                }

                // shader params
                uint32_t param_count;
                if (!read_u32(param_count)) goto done_dc;
                if (param_count > 256) param_count = 256; // sanity
                dc.params.reserve(param_count);
                for (uint32_t p = 0; p < param_count; ++p) {
                    store::RawDrawCall::Param param{};
                    uint32_t loc, type, dsz;
                    if (!read_u32(loc))  goto done_dc;
                    if (!read_u32(type)) goto done_dc;
                    if (!read_u32(dsz))  goto done_dc;
                    if (dsz > 64) goto done_dc; // sanity: max uniform is mat4 = 64 bytes
                    param.type = type;
                    if (dsz > 0) {
                        if (dc_ptr + dsz > dc_end) goto done_dc;
                        param.data.assign(dc_ptr, dc_ptr + dsz);
                        dc_ptr += dsz;
                    }
                    // Generate a name from the uniform location if no name was
                    // serialised by the shim (name query requires GL context).
                    param.name = "uniform_" + std::to_string(loc);
                    dc.params.push_back(std::move(param));
                }

                frame.draw_calls.push_back(std::move(dc));
            }
            done_dc:;
        }
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
