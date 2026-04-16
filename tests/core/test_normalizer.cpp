#include <gtest/gtest.h>
#include "src/core/normalize/normalizer.h"

TEST(NormalizerTest, Normalize) {
    gla::normalize::Normalizer n;
    gla::store::RawFrame f{0, 0};
    auto dc = n.normalize(f);
    EXPECT_EQ(dc.call_id, 0u);
}
