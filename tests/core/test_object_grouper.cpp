#include <gtest/gtest.h>
#include "src/core/semantic/object_grouper.h"
#include "src/core/normalize/normalized_types.h"

namespace gla {

class ObjectGrouperTest : public ::testing::Test {
protected:
    ObjectGrouper grouper_;
};

TEST_F(ObjectGrouperTest, GroupEmptyFrame) {
    // TODO(M3): Implement object grouping tests
    NormalizedFrame frame;
    frame.frame_id = 1;
    frame.timestamp = 0.0;
    
    auto result = grouper_.group(frame);
    EXPECT_TRUE(result.empty());
}

}  // namespace gla
