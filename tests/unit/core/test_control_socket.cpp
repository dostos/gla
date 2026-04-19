#include <gtest/gtest.h>

#include "src/core/ipc/control_socket.h"
#include "src/core/ipc/protocol.h"

#include <arpa/inet.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstring>
#include <string>
#include <thread>
#include <chrono>

static const std::string kSockPath = "/tmp/gla_test_ctrl.sock";

// Helper: remove socket file before each test to keep tests hermetic.
class ControlSocketTest : public ::testing::Test {
protected:
    void SetUp() override { ::unlink(kSockPath.c_str()); }
    void TearDown() override { ::unlink(kSockPath.c_str()); }
};

// ---------------------------------------------------------------------------
// 1. ServerStartsListening
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, ServerStartsListening) {
    gla::ipc::ControlSocketServer server(kSockPath);
    EXPECT_GE(server.fd(), 0) << "Server fd should be valid";

    struct stat st{};
    EXPECT_EQ(::stat(kSockPath.c_str(), &st), 0) << "Socket file should exist";
    EXPECT_TRUE(S_ISSOCK(st.st_mode)) << "Should be a socket file";
}

// ---------------------------------------------------------------------------
// 2. ClientConnects
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, ClientConnects) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    gla::ipc::ControlSocketClient client;
    EXPECT_TRUE(client.connect(kSockPath));

    // Give the server a moment then accept
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    int cfd = server.accept_client();
    EXPECT_GE(cfd, 0) << "Server should accept the connection";
    if (cfd >= 0) ::close(cfd);
}

// ---------------------------------------------------------------------------
// 3. HandshakeSuccess — client sends v1 → server sends OK → client sees OK
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, HandshakeSuccess) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    // Client runs in background thread
    bool client_ok = false;
    std::thread client_thread([&]() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return;
        if (!client.send_handshake(/*api_type=*/0, /*pid=*/1234)) return;
        client_ok = client.wait_handshake_response();
    });

    // Server: accept, read handshake, validate, respond
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    int cfd = -1;
    for (int i = 0; i < 50 && cfd < 0; ++i) {
        cfd = server.accept_client();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_GE(cfd, 0);

    gla::ipc::MsgType type{};
    std::vector<uint8_t> payload;
    ASSERT_TRUE(server.read_message(cfd, type, payload));
    EXPECT_EQ(type, gla::ipc::MsgType::MSG_HANDSHAKE);
    ASSERT_EQ(payload.size(), sizeof(gla::ipc::HandshakePayload));

    gla::ipc::HandshakePayload hs{};
    std::memcpy(&hs, payload.data(), sizeof(hs));
    uint32_t version = ntohl(hs.protocol_version);
    EXPECT_EQ(version, gla::ipc::PROTOCOL_VERSION);

    // Send OK
    server.send_message(cfd, gla::ipc::MsgType::MSG_HANDSHAKE_OK, nullptr, 0);
    ::close(cfd);

    client_thread.join();
    EXPECT_TRUE(client_ok);
}

// ---------------------------------------------------------------------------
// 4. HandshakeVersionMismatch — client sends wrong version → server sends FAIL
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, HandshakeVersionMismatch) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    bool client_rejected = false;
    std::thread client_thread([&]() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return;
        // Manually craft a bad-version handshake
        gla::ipc::HandshakePayload p{};
        p.protocol_version = htonl(99);  // wrong version
        p.api_type         = htonl(0);
        p.pid              = htonl(5678);
        // Use send_message via friend access — we'll call the public method which
        // always sends PROTOCOL_VERSION; build the message manually via send_frame.
        // Instead, connect at the raw fd level after obtaining it.
        // Easiest: subclass or just send manually.
        // We expose fd() so we can write directly.
        int fd = client.fd();
        if (fd < 0) return;
        // Build framed message manually
        uint32_t len_be = htonl(1 + static_cast<uint32_t>(sizeof(p)));
        ::write(fd, &len_be, 4);
        uint8_t type_byte = static_cast<uint8_t>(gla::ipc::MsgType::MSG_HANDSHAKE);
        ::write(fd, &type_byte, 1);
        ::write(fd, &p, sizeof(p));

        // wait for response (blocking read)
        uint32_t rlen_be = 0;
        if (::read(fd, &rlen_be, 4) != 4) return;
        uint8_t rtype = 0;
        ::read(fd, &rtype, 1);
        client_rejected = (rtype == static_cast<uint8_t>(gla::ipc::MsgType::MSG_HANDSHAKE_FAIL));
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    int cfd = -1;
    for (int i = 0; i < 50 && cfd < 0; ++i) {
        cfd = server.accept_client();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_GE(cfd, 0);

    gla::ipc::MsgType type{};
    std::vector<uint8_t> payload;
    ASSERT_TRUE(server.read_message(cfd, type, payload));
    EXPECT_EQ(type, gla::ipc::MsgType::MSG_HANDSHAKE);
    ASSERT_EQ(payload.size(), sizeof(gla::ipc::HandshakePayload));

    gla::ipc::HandshakePayload hs{};
    std::memcpy(&hs, payload.data(), sizeof(hs));
    uint32_t version = ntohl(hs.protocol_version);
    EXPECT_NE(version, gla::ipc::PROTOCOL_VERSION);

    server.send_message(cfd, gla::ipc::MsgType::MSG_HANDSHAKE_FAIL, nullptr, 0);
    ::close(cfd);

    client_thread.join();
    EXPECT_TRUE(client_rejected);
}

// ---------------------------------------------------------------------------
// 5. FrameReadyMessage — client sends frame_ready(42, 2) → server reads correctly
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, FrameReadyMessage) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    std::thread client_thread([&]() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return;
        client.send_frame_ready(42, 2);
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    int cfd = -1;
    for (int i = 0; i < 50 && cfd < 0; ++i) {
        cfd = server.accept_client();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_GE(cfd, 0);

    gla::ipc::MsgType type{};
    std::vector<uint8_t> payload;
    ASSERT_TRUE(server.read_message(cfd, type, payload));
    EXPECT_EQ(type, gla::ipc::MsgType::MSG_FRAME_READY);
    ASSERT_EQ(payload.size(), sizeof(gla::ipc::FrameReadyPayload));

    // Decode payload (native endian — matches C shim and C++ client)
    gla::ipc::FrameReadyPayload fr{};
    std::memcpy(&fr, payload.data(), sizeof(fr));
    EXPECT_EQ(fr.frame_id, 42u);
    EXPECT_EQ(fr.shm_slot_index, 2u);

    ::close(cfd);
    client_thread.join();
}

// ---------------------------------------------------------------------------
// 6. ControlMessage — server sends pause command → client reads it
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, ControlMessage) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    gla::ipc::ControlPayload received{};
    bool client_got_control = false;

    std::thread client_thread([&]() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return;
        // Wait briefly then poll
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        for (int i = 0; i < 100; ++i) {
            if (client.read_control(received)) {
                client_got_control = true;
                return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    int cfd = -1;
    for (int i = 0; i < 50 && cfd < 0; ++i) {
        cfd = server.accept_client();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_GE(cfd, 0);

    // Build control payload (network byte order for step_frames)
    gla::ipc::ControlPayload ctrl{};
    ctrl.pause       = 1;
    ctrl.resume      = 0;
    ctrl.step_frames = htonl(0);
    server.send_message(cfd, gla::ipc::MsgType::MSG_CONTROL, &ctrl, sizeof(ctrl));

    client_thread.join();
    ::close(cfd);

    EXPECT_TRUE(client_got_control);
    EXPECT_EQ(received.pause, 1);
    EXPECT_EQ(received.resume, 0);
    EXPECT_EQ(received.step_frames, 0u);
}

// ---------------------------------------------------------------------------
// 7. MultipleMessages — several frame_ready in sequence → all received
// ---------------------------------------------------------------------------
TEST_F(ControlSocketTest, MultipleMessages) {
    gla::ipc::ControlSocketServer server(kSockPath);
    ASSERT_GE(server.fd(), 0);

    static const int kN = 5;
    std::thread client_thread([&]() {
        gla::ipc::ControlSocketClient client;
        if (!client.connect(kSockPath)) return;
        for (int i = 0; i < kN; ++i) {
            client.send_frame_ready(static_cast<uint64_t>(i) * 10, static_cast<uint32_t>(i));
        }
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    int cfd = -1;
    for (int i = 0; i < 50 && cfd < 0; ++i) {
        cfd = server.accept_client();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_GE(cfd, 0);

    for (int i = 0; i < kN; ++i) {
        gla::ipc::MsgType type{};
        std::vector<uint8_t> payload;
        ASSERT_TRUE(server.read_message(cfd, type, payload)) << "Message " << i;
        EXPECT_EQ(type, gla::ipc::MsgType::MSG_FRAME_READY) << "Message " << i;
        ASSERT_EQ(payload.size(), sizeof(gla::ipc::FrameReadyPayload));

        gla::ipc::FrameReadyPayload fr{};
        std::memcpy(&fr, payload.data(), sizeof(fr));
        EXPECT_EQ(fr.frame_id, static_cast<uint64_t>(i) * 10) << "Message " << i;
        EXPECT_EQ(fr.shm_slot_index, static_cast<uint32_t>(i)) << "Message " << i;
    }

    ::close(cfd);
    client_thread.join();
}
