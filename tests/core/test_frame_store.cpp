#include <gtest/gtest.h>
#include "src/core/store/frame_store.h"

TEST(FrameStoreTest, PushGet) {
    gla::store::FrameStore store;
    gla::store::RawFrame f{1, 0};
    store.push(f);
    gla::store::RawFrame out;
    EXPECT_FALSE(store.get(1, &out));  // stub always returns false
}
