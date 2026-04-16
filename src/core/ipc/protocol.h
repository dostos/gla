#pragma once
#include <cstdint>

namespace gla::ipc {

enum class MessageType : uint8_t {
    NOOP = 0,
    FRAME_START = 1,
    FRAME_END = 2,
};

} // namespace gla::ipc
