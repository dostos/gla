#pragma once
#include "src/core/store/raw_frame.h"

namespace gla::store {

class FrameStore {
public:
    FrameStore() = default;
    ~FrameStore() = default;
    void push(const RawFrame &f);
    bool get(uint64_t frame_id, RawFrame *out) const;
};

} // namespace gla::store
