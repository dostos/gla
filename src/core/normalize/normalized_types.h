#pragma once
#include <cstdint>

namespace gla::normalize {

struct NormalizedDrawCall {
    uint64_t call_id;
    uint32_t gl_command;
};

} // namespace gla::normalize
