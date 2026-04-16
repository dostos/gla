#include <gtest/gtest.h>
#include "src/core/semantic/matrix_classifier.h"

namespace gla {

class MatrixClassifierTest : public ::testing::Test {
protected:
    MatrixClassifier classifier_;
};

TEST_F(MatrixClassifierTest, ClassifyUnknown) {
    // TODO(M3): Implement matrix classification tests
    const float data[] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    auto result = classifier_.classify("uUnknown", data);
    EXPECT_EQ(result.semantic, MatrixClassifier::MatrixSemantic::Unknown);
}

}  // namespace gla
