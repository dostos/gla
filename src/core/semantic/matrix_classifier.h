#pragma once
#include <string>

namespace gla {

class MatrixClassifier {
public:
    enum class MatrixSemantic {
        Unknown,
        Model,
        View,
        Projection,
        MVP,
        Normal
    };

    struct Classification {
        MatrixSemantic semantic;
        float confidence;  // 0.0-1.0
    };

    /**
     * Classify a matrix based on its name and data.
     *
     * @param name The name of the matrix (e.g., "uModel", "uViewProj").
     * @param data Pointer to matrix data (for semantic analysis).
     * @return Classification result with semantic type and confidence.
     */
    Classification classify(const std::string& name, const float* data) const;
};

}  // namespace gla
