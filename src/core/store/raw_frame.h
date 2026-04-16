#pragma once
#include <cstdint>

namespace gla::store {

struct RawFrame {
    uint64_t frame_id;
    uint64_t timestamp_ns;
};

} // namespace gla::store
