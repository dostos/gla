#include "src/core/semantic/matrix_classifier.h"

namespace gla {

MatrixClassifier::Classification MatrixClassifier::classify(const std::string& name, const float* data) const {
    // Stub implementation: return Unknown classification
    // TODO(M3): Implement matrix semantic analysis
    return Classification{MatrixSemantic::Unknown, 0.0f};
}

}  // namespace gla
