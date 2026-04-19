#include <gtest/gtest.h>

#include <sys/mman.h>
#include <fcntl.h>

#include <atomic>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "src/core/ipc/shm_ring_buffer.h"

// Helper: returns true if the POSIX shm segment `name` currently exists.
static bool shm_exists(const std::string& name) {
    int fd = ::shm_open(name.c_str(), O_RDONLY, 0);
    if (fd == -1) return false;
    ::close(fd);
    return true;
}

// Use a unique name per test to avoid cross-test pollution.
static std::string unique_shm_name(const char* suffix) {
    return std::string("/gla_test_") + suffix;
}

// ── 1. CreateAndDestroy ───────────────────────────────────────────────────────

TEST(ShmRingBufferTest, CreateAndDestroy) {
    const std::string name = unique_shm_name("create_destroy");
    ::shm_unlink(name.c_str()); // pre-clean

    {
        auto rb = gla::ShmRingBuffer::create(name, 4, 512);
        ASSERT_NE(rb, nullptr);
        EXPECT_TRUE(shm_exists(name)) << "shm segment should exist after create()";
    } // destructor runs here

    EXPECT_FALSE(shm_exists(name)) << "shm segment should be unlinked after owner destroy";
}

// ── 2. OpenExisting ───────────────────────────────────────────────────────────

TEST(ShmRingBufferTest, OpenExisting) {
    const std::string name = unique_shm_name("open_existing");
    ::shm_unlink(name.c_str());

    auto owner = gla::ShmRingBuffer::create(name, 4, 64);
    ASSERT_NE(owner, nullptr);

    auto client = gla::ShmRingBuffer::open(name);
    ASSERT_NE(client, nullptr);

    EXPECT_EQ(client->num_slots(), owner->num_slots());
    EXPECT_EQ(client->slot_size(),  owner->slot_size());
}

// ── 3. WriteAndRead ───────────────────────────────────────────────────────────

TEST(ShmRingBufferTest, WriteAndRead) {
    const std::string name = unique_shm_name("write_read");
    ::shm_unlink(name.c_str());

    auto rb = gla::ShmRingBuffer::create(name, 4, 64);
    ASSERT_NE(rb, nullptr);

    // Writer: claim → fill → commit
    auto ws = rb->claim_write_slot();
    ASSERT_NE(ws.data, nullptr);
    const char msg[] = "hello";
    std::memcpy(ws.data, msg, sizeof(msg));
    rb->commit_write(ws.index, sizeof(msg));

    // Reader: claim → verify → release
    auto rs = rb->claim_read_slot();
    ASSERT_NE(rs.data, nullptr);
    EXPECT_EQ(rs.size, sizeof(msg));
    EXPECT_STREQ(static_cast<const char*>(rs.data), "hello");
    rb->release_read(rs.index);
}

// ── 4. FullRingReturnsNull ────────────────────────────────────────────────────

TEST(ShmRingBufferTest, FullRingReturnsNull) {
    const std::string name = unique_shm_name("full_ring");
    ::shm_unlink(name.c_str());

    constexpr uint32_t N = 3;
    auto rb = gla::ShmRingBuffer::create(name, N, 64);
    ASSERT_NE(rb, nullptr);

    // Fill all slots.
    for (uint32_t i = 0; i < N; ++i) {
        auto ws = rb->claim_write_slot();
        ASSERT_NE(ws.data, nullptr) << "should claim slot " << i;
        rb->commit_write(ws.index, 1);
    }

    // One more claim should fail.
    auto ws = rb->claim_write_slot();
    EXPECT_EQ(ws.data, nullptr) << "ring is full; claim_write_slot should return nullptr";
}

// ── 5. MultipleWriteReadCycles ────────────────────────────────────────────────

TEST(ShmRingBufferTest, MultipleWriteReadCycles) {
    const std::string name = unique_shm_name("multi_cycle");
    ::shm_unlink(name.c_str());

    auto rb = gla::ShmRingBuffer::create(name, 4, 64);
    ASSERT_NE(rb, nullptr);

    for (int round = 0; round < 20; ++round) {
        uint64_t payload = static_cast<uint64_t>(round) * 0xDEADBEEF;

        auto ws = rb->claim_write_slot();
        ASSERT_NE(ws.data, nullptr) << "round " << round;
        std::memcpy(ws.data, &payload, sizeof(payload));
        rb->commit_write(ws.index, sizeof(payload));

        auto rs = rb->claim_read_slot();
        ASSERT_NE(rs.data, nullptr) << "round " << round;
        uint64_t received = 0;
        std::memcpy(&received, rs.data, sizeof(received));
        EXPECT_EQ(received, payload) << "round " << round;
        rb->release_read(rs.index);
    }
}

// ── 6. ConcurrentAccess ───────────────────────────────────────────────────────

TEST(ShmRingBufferTest, ConcurrentAccess) {
    const std::string name = unique_shm_name("concurrent");
    ::shm_unlink(name.c_str());

    constexpr int      MESSAGES    = 1000;
    constexpr uint32_t NUM_SLOTS   = 8;
    constexpr size_t   SLOT_SIZE   = 64;

    auto rb = gla::ShmRingBuffer::create(name, NUM_SLOTS, SLOT_SIZE);
    ASSERT_NE(rb, nullptr);

    std::atomic<int> written{0};
    std::atomic<int> read_count{0};

    // Writer thread: keep writing until MESSAGES frames are committed.
    std::thread writer([&] {
        int sent = 0;
        while (sent < MESSAGES) {
            auto ws = rb->claim_write_slot();
            if (ws.data == nullptr) {
                std::this_thread::yield();
                continue;
            }
            uint32_t val = static_cast<uint32_t>(sent);
            std::memcpy(ws.data, &val, sizeof(val));
            rb->commit_write(ws.index, sizeof(val));
            ++sent;
            written.fetch_add(1, std::memory_order_relaxed);
        }
    });

    // Reader thread: keep reading until MESSAGES frames are processed.
    std::thread reader([&] {
        int received = 0;
        while (received < MESSAGES) {
            auto rs = rb->claim_read_slot();
            if (rs.data == nullptr) {
                std::this_thread::yield();
                continue;
            }
            rb->release_read(rs.index);
            ++received;
            read_count.fetch_add(1, std::memory_order_relaxed);
        }
    });

    writer.join();
    reader.join();

    EXPECT_EQ(written.load(), MESSAGES);
    EXPECT_EQ(read_count.load(), MESSAGES);
}

// ── 7. ClientCanWriteAndRead (cross-process simulation) ───────────────────────

TEST(ShmRingBufferTest, ClientCanWriteAndRead) {
    const std::string name = unique_shm_name("cross_process");
    ::shm_unlink(name.c_str());

    auto owner  = gla::ShmRingBuffer::create(name, 4, 64);
    auto client = gla::ShmRingBuffer::open(name);
    ASSERT_NE(owner,  nullptr);
    ASSERT_NE(client, nullptr);

    // Client writes, owner reads.
    const char msg[] = "cross";
    auto ws = client->claim_write_slot();
    ASSERT_NE(ws.data, nullptr);
    std::memcpy(ws.data, msg, sizeof(msg));
    client->commit_write(ws.index, sizeof(msg));

    auto rs = owner->claim_read_slot();
    ASSERT_NE(rs.data, nullptr);
    EXPECT_STREQ(static_cast<const char*>(rs.data), "cross");
    owner->release_read(rs.index);
}

// ── 8. StaleShmHandledGracefully ─────────────────────────────────────────────

TEST(ShmRingBufferTest, StaleShmHandledGracefully) {
    const std::string name = unique_shm_name("stale");

    // Leave a stale segment behind.
    {
        int fd = ::shm_open(name.c_str(), O_CREAT | O_RDWR, 0600);
        ASSERT_NE(fd, -1);
        ::ftruncate(fd, 4096);
        ::close(fd);
    }
    ASSERT_TRUE(shm_exists(name));

    // create() should silently unlink the stale segment and succeed.
    EXPECT_NO_THROW({
        auto rb = gla::ShmRingBuffer::create(name, 2, 64);
        EXPECT_NE(rb, nullptr);
    });
}
