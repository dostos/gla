#pragma once
#include <cstddef>

namespace gla::ipc {

class ShmRingBuffer {
public:
    ShmRingBuffer() = default;
    ~ShmRingBuffer() = default;
    bool write(const void *data, size_t len);
    bool read(void *buf, size_t len);
};

} // namespace gla::ipc
