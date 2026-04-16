#include <gtest/gtest.h>
#include "src/core/semantic/camera_extractor.h"
#include "src/core/normalize/normalized_types.h"

namespace gla {

class CameraExtractorTest : public ::testing::Test {
protected:
    CameraExtractor extractor_;
};

TEST_F(CameraExtractorTest, ExtractFromEmptyFrame) {
    // TODO(M3): Implement camera extraction tests
    NormalizedFrame frame;
    frame.frame_id = 1;
    frame.timestamp = 0.0;
    
    auto result = extractor_.extract(frame);
    // Stub: expect no camera info from empty frame
    EXPECT_FALSE(result.has_value());
}

}  // namespace gla
