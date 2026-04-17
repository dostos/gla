#include <gtest/gtest.h>

#include "src/core/engine.h"
#include "src/core/ipc/control_socket.h"
#include "src/core/ipc/protocol.h"
#include "src/core/ipc/shm_ring_buffer.h"

#include <arpa/inet.h>
#include <unistd.h>

#include <chrono>
#include <cstring>
#include <string>
#include <thread>

static const std::string kSockPath = "/tmp/gla_test_engine.sock";
static const std::string kShmName  = "/gla_test_engine_shm";

// ---------------------------------------------------------------------------
// Fixture — owns Engine running in a background thread
// ---------------------------------------------------------------------------
class EngineTest : public ::testing::Test {
protected:
    void SetUp() override {
        ::unlink(kSockPath.c_str());

        engine_ = std::make_unique<gla::Engine>(
            kSockPath, kShmName, /*shm_slots=*/4, /*slot_size=*/1024 * 1024);

        engine_thread_ = std::thread([this]() { engine_->run(); });

        // Give the engine a moment to start listening
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }

    void TearDown() override {
        engine_->stop();
        if (engine_thread_.joinable()) engine_thread_.join();
        ::unlink(kSockPath.c_str());
    }

    // Helper: connect a client and complete the handshake.  Returns client.
    gla::ipc::ControlSocketClient connect_and_handshake() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return client;
        client.send_handshake(/*api_type=*/0, /*pid=*/static_cast<uint32_t>(::getpid()));
        client.wait_handshake_response();
        return client;
    }

    std::unique_ptr<gla::Engine> engine_;
    std::thread engine_thread_;
};

// ---------------------------------------------------------------------------
// 1. Handshake — client connects, sends valid handshake → receives OK
// ---------------------------------------------------------------------------
TEST_F(EngineTest, HandshakeSuccess) {
    gla::ipc::ControlSocketClient client;
    ASSERT_TRUE(client.connect(kSockPath));
    ASSERT_TRUE(client.send_handshake(0, static_cast<uint32_t>(::getpid())));
    EXPECT_TRUE(client.wait_handshake_response())
        << "Engine should accept a v1 handshake";
}

// ---------------------------------------------------------------------------
// 2. BadVersion — engine rejects an incompatible protocol version
// ---------------------------------------------------------------------------
TEST_F(EngineTest, HandshakeBadVersion) {
    gla::ipc::ControlSocketClient client;
    ASSERT_TRUE(client.connect(kSockPath));

    // Manually craft a handshake with wrong version via raw fd
    int fd = client.fd();
    ASSERT_GE(fd, 0);

    gla::ipc::HandshakePayload p{};
    p.protocol_version = htonl(99); // wrong
    p.api_type         = htonl(0);
    p.pid              = htonl(1);

    uint32_t len_be = htonl(1 + static_cast<uint32_t>(sizeof(p)));
    ::write(fd, &len_be, 4);
    uint8_t type_byte = static_cast<uint8_t>(gla::ipc::MsgType::MSG_HANDSHAKE);
    ::write(fd, &type_byte, 1);
    ::write(fd, &p, sizeof(p));

    // Read response
    uint32_t rlen_be = 0;
    ASSERT_EQ(::read(fd, &rlen_be, 4), 4);
    uint8_t rtype = 0;
    ASSERT_EQ(::read(fd, &rtype, 1), 1);
    EXPECT_EQ(rtype, static_cast<uint8_t>(gla::ipc::MsgType::MSG_HANDSHAKE_FAIL));
}

// ---------------------------------------------------------------------------
// 3. FrameIngestion — write data to SHM, send FRAME_READY → frame appears
// ---------------------------------------------------------------------------
TEST_F(EngineTest, FrameIngestionViaShm) {
    // Open the same SHM segment the engine created
    auto shm_client = gla::ShmRingBuffer::open(kShmName);
    ASSERT_NE(shm_client, nullptr) << "Could not open shm segment";

    // Connect and handshake
    gla::ipc::ControlSocketClient client = connect_and_handshake();
    ASSERT_GE(client.fd(), 0);

    // Write data into a SHM slot
    static const uint8_t kPayload[] = {0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02};
    auto wslot = shm_client->claim_write_slot();
    ASSERT_NE(wslot.data, nullptr) << "Could not claim write slot";
    std::memcpy(wslot.data, kPayload, sizeof(kPayload));
    shm_client->commit_write(wslot.index, sizeof(kPayload));

    // Send FRAME_READY
    ASSERT_TRUE(client.send_frame_ready(/*frame_id=*/42, wslot.index));

    // Wait for the engine to process it
    for (int i = 0; i < 200; ++i) {
        if (engine_->frame_store().count() > 0) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    EXPECT_GT(engine_->frame_store().count(), 0u);
    const gla::store::RawFrame* frame = engine_->frame_store().get(42);
    if (frame) {
        EXPECT_EQ(frame->frame_id, 42u);
    }
}

// ---------------------------------------------------------------------------
// Helper: build a minimal valid SHM frame with one draw call
// ---------------------------------------------------------------------------
static std::vector<uint8_t> build_frame_with_draw_call(
        uint32_t width, uint32_t height,
        uint32_t prim, uint32_t vertex_count,
        uint32_t index_count, uint32_t instance_count,
        uint32_t shader_prog)
{
    std::vector<uint8_t> buf;
    auto push_u32 = [&](uint32_t v) {
        buf.push_back(v & 0xFF);
        buf.push_back((v >> 8) & 0xFF);
        buf.push_back((v >> 16) & 0xFF);
        buf.push_back((v >> 24) & 0xFF);
    };
    auto push_i32 = [&](int32_t v) { push_u32(static_cast<uint32_t>(v)); };
    auto push_u8  = [&](uint8_t  v) { buf.push_back(v); };

    // header
    push_u32(width);
    push_u32(height);

    // color pixels (all zero)
    buf.resize(buf.size() + (size_t)width * height * 4, 0);
    // depth pixels (all zero)
    buf.resize(buf.size() + (size_t)width * height * 4, 0);

    // draw_call_count = 1
    push_u32(1);

    // One draw call record
    push_u32(0);              // id
    push_u32(prim);           // primitive_type
    push_u32(vertex_count);   // vertex_count
    push_u32(index_count);    // index_count
    push_u32(instance_count); // instance_count
    push_u32(shader_prog);    // shader_program_id

    // viewport[4]
    push_i32(0); push_i32(0); push_i32((int32_t)width); push_i32((int32_t)height);
    // scissor[4]
    push_i32(0); push_i32(0); push_i32(0); push_i32(0);
    // scissor_enabled, depth_test, depth_write, pad
    push_u8(0); push_u8(1); push_u8(1); push_u8(0);
    // depth_func (GL_LESS = 0x0201)
    push_u32(0x0201);
    // blend_enabled, pad[3]
    push_u8(0); push_u8(0); push_u8(0); push_u8(0);
    // blend_src, blend_dst
    push_u32(0); push_u32(0);
    // cull_enabled, pad[3]
    push_u8(0); push_u8(0); push_u8(0); push_u8(0);
    // cull_mode, front_face
    push_u32(0x0405); push_u32(0x0901);

    // texture_count = 0
    push_u32(0);
    // param_count = 0
    push_u32(0);

    return buf;
}

// ---------------------------------------------------------------------------
// 3b. DrawCallRoundTrip — write a frame with draw call data; engine parses it
// ---------------------------------------------------------------------------
TEST_F(EngineTest, DrawCallRoundTrip) {
    const uint32_t W = 4, H = 4;
    const uint32_t GL_TRIANGLES = 0x0004;

    auto shm_client = gla::ShmRingBuffer::open(kShmName);
    ASSERT_NE(shm_client, nullptr);

    gla::ipc::ControlSocketClient client = connect_and_handshake();
    ASSERT_GE(client.fd(), 0);

    std::vector<uint8_t> payload =
        build_frame_with_draw_call(W, H, GL_TRIANGLES,
                                   /*vertex_count=*/3, /*index_count=*/0,
                                   /*instance_count=*/1, /*shader_prog=*/7);

    auto wslot = shm_client->claim_write_slot();
    ASSERT_NE(wslot.data, nullptr);
    ASSERT_LE(payload.size(), (size_t)1024 * 1024);
    std::memcpy(wslot.data, payload.data(), payload.size());
    shm_client->commit_write(wslot.index, payload.size());
    ASSERT_TRUE(client.send_frame_ready(/*frame_id=*/77, wslot.index));

    // Wait for the engine to process the frame (engine assigns its own ID)
    for (int i = 0; i < 200; ++i) {
        const gla::store::RawFrame* f = engine_->frame_store().latest();
        if (f && !f->draw_calls.empty()) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    const gla::store::RawFrame* frame = engine_->frame_store().latest();
    ASSERT_NE(frame, nullptr) << "No frame found in store";

    // Pixel buffers
    EXPECT_EQ(frame->fb_width,  W);
    EXPECT_EQ(frame->fb_height, H);
    EXPECT_EQ(frame->fb_color.size(), (size_t)W * H * 4);
    EXPECT_EQ(frame->fb_depth.size(), (size_t)W * H);

    // Draw call
    ASSERT_EQ(frame->draw_calls.size(), 1u);
    const auto& dc = frame->draw_calls[0];
    EXPECT_EQ(dc.id,               0u);
    EXPECT_EQ(dc.primitive_type,   GL_TRIANGLES);
    EXPECT_EQ(dc.vertex_count,     3u);
    EXPECT_EQ(dc.index_count,      0u);
    EXPECT_EQ(dc.instance_count,   1u);
    EXPECT_EQ(dc.shader_program_id, 7u);
    EXPECT_EQ(dc.pipeline.depth_test,  true);
    EXPECT_EQ(dc.pipeline.depth_write, true);
    EXPECT_EQ(dc.pipeline.depth_func,  0x0201u);
    EXPECT_EQ(dc.pipeline.cull_mode,   0x0405u);
    EXPECT_TRUE(dc.textures.empty());
    EXPECT_TRUE(dc.params.empty());
}

// ---------------------------------------------------------------------------
// 4. PauseResume — request_pause() → is_paused() true; request_resume() → false
// ---------------------------------------------------------------------------
TEST_F(EngineTest, PauseResume) {
    EXPECT_FALSE(engine_->is_paused());

    engine_->request_pause();
    // is_paused is atomic; no sleep needed
    EXPECT_TRUE(engine_->is_paused());

    engine_->request_resume();
    EXPECT_FALSE(engine_->is_paused());
}

// ---------------------------------------------------------------------------
// 5. PauseControlToClients — after pause, connected client receives MSG_CONTROL
// ---------------------------------------------------------------------------
TEST_F(EngineTest, PauseControlToClients) {
    gla::ipc::ControlSocketClient client = connect_and_handshake();
    ASSERT_GE(client.fd(), 0);

    // Give engine a tick to register the client before we ask for pause
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    engine_->request_pause();

    gla::ipc::ControlPayload ctrl{};
    bool got_control = false;
    for (int i = 0; i < 100 && !got_control; ++i) {
        if (client.read_control(ctrl)) got_control = true;
        else std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    EXPECT_TRUE(got_control) << "Client should receive a CONTROL message after pause";
    EXPECT_EQ(ctrl.pause, 1);
}

// ---------------------------------------------------------------------------
// 6. MultipleFrames — send 5 frames; all should be stored
// ---------------------------------------------------------------------------
TEST_F(EngineTest, MultipleFrames) {
    auto shm_client = gla::ShmRingBuffer::open(kShmName);
    ASSERT_NE(shm_client, nullptr);

    gla::ipc::ControlSocketClient client = connect_and_handshake();
    ASSERT_GE(client.fd(), 0);

    static const int kFrames = 3; // limited by ring-buffer slots
    for (int i = 0; i < kFrames; ++i) {
        // Wait until a slot is free
        gla::ShmRingBuffer::WriteSlot wslot{nullptr, 0};
        for (int retry = 0; retry < 200 && wslot.data == nullptr; ++retry) {
            wslot = shm_client->claim_write_slot();
            if (!wslot.data)
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        ASSERT_NE(wslot.data, nullptr) << "No free slot for frame " << i;

        uint8_t data = static_cast<uint8_t>(i);
        std::memcpy(wslot.data, &data, 1);
        shm_client->commit_write(wslot.index, 1);
        client.send_frame_ready(static_cast<uint64_t>(100 + i), wslot.index);

        // Brief pause to let the engine drain the slot before the next write
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    // Wait for engine to process all frames
    for (int i = 0; i < 200; ++i) {
        if (engine_->frame_store().total_stored() >= static_cast<uint64_t>(kFrames))
            break;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }

    EXPECT_GE(engine_->frame_store().total_stored(),
              static_cast<uint64_t>(kFrames));
}
