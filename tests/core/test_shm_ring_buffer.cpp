#include <gtest/gtest.h>
#include "src/core/ipc/shm_ring_buffer.h"

TEST(ShmRingBufferTest, WriteRead) {
    gla::ipc::ShmRingBuffer buf;
    uint8_t data[4] = {1, 2, 3, 4};
    EXPECT_TRUE(buf.write(data, sizeof(data)));
}
