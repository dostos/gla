#pragma once
#include <string>
#include <unordered_map>
#include "src/core/normalize/normalized_types.h"

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
     * Classify a matrix based on its name and data (two-pass: name then structure).
     *
     * @param name The uniform name (e.g., "uModelMatrix").
     * @param data Pointer to 16 floats in column-major order.
     * @return Classification result with semantic type and confidence.
     */
    Classification classify(const std::string& name, const float* data) const;

    /**
     * Classify all mat4 params across a frame using cross-draw-call heuristics.
     * Adds change-rate analysis on top of the per-matrix classify().
     *
     * @param frame A fully normalised frame.
     * @return Map from param name to Classification.
     */
    std::unordered_map<std::string, Classification>
    classify_frame(const NormalizedFrame& frame) const;

    // ---- helpers (public so tests can exercise them directly) ----

    /// Returns true if the upper-left 3x3 of a column-major mat4 is orthonormal.
    static bool is_orthonormal_3x3(const float* mat, float eps = 0.01f);

    /// Returns true if the matrix has the perspective-projection pattern.
    static bool is_perspective_projection(const float* mat, float eps = 0.01f);

    /// Returns true if the matrix has the orthographic-projection pattern.
    static bool is_orthographic_projection(const float* mat, float eps = 0.01f);

    /// Case-insensitive substring search.
    static bool name_contains(const std::string& name, const std::string& pattern);

private:
    /// Pass 1: try to match by name. Returns {Unknown, 0} on no match.
    static Classification classify_by_name(const std::string& name);

    /// Pass 2: try to match by matrix structure. Returns {Unknown, 0} on no match.
    static Classification classify_by_structure(const float* data);
};

}  // namespace gla
