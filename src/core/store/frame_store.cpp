// Frame store — stub
#include "src/core/store/frame_store.h"

namespace gla::store {

void FrameStore::push(const RawFrame &f) { (void)f; }
bool FrameStore::get(uint64_t frame_id, RawFrame *out) const {
    (void)frame_id; (void)out; return false;
}

} // namespace gla::store
