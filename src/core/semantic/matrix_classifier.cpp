#include "src/core/semantic/matrix_classifier.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <unordered_set>

namespace gla {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

bool MatrixClassifier::name_contains(const std::string& name,
                                     const std::string& pattern) {
    // Case-insensitive substring search
    auto it = std::search(
        name.begin(), name.end(),
        pattern.begin(), pattern.end(),
        [](unsigned char a, unsigned char b) {
            return std::tolower(a) == std::tolower(b);
        });
    return it != name.end();
}

// Column-major indexing: element at row r, col c  →  data[c*4 + r]
static inline float m(const float* d, int row, int col) {
    return d[col * 4 + row];
}

bool MatrixClassifier::is_orthonormal_3x3(const float* mat, float eps) {
    // Each of the three column vectors of the upper-left 3×3 must have unit
    // length, and every pair must be orthogonal.
    for (int c = 0; c < 3; ++c) {
        float len_sq = 0.0f;
        for (int r = 0; r < 3; ++r) {
            float v = m(mat, r, c);
            len_sq += v * v;
        }
        if (std::fabs(len_sq - 1.0f) > eps) return false;
    }
    // Orthogonality of pairs
    for (int c1 = 0; c1 < 3; ++c1) {
        for (int c2 = c1 + 1; c2 < 3; ++c2) {
            float dot = 0.0f;
            for (int r = 0; r < 3; ++r) {
                dot += m(mat, r, c1) * m(mat, r, c2);
            }
            if (std::fabs(dot) > eps) return false;
        }
    }
    return true;
}

bool MatrixClassifier::is_perspective_projection(const float* mat, float eps) {
    // Standard OpenGL perspective matrix (column-major storage):
    //   Column 2: [0, 0, (f+n)/(n-f), -1]   → row3 = -1, i.e. mat[2*4+3]=mat[11]=-1
    //   Column 3: [0, 0, 2fn/(n-f),    0]   → row2 ≠ 0, i.e. mat[3*4+2]=mat[14]≠0
    //
    // m(row, col) = mat[col*4 + row]
    //   m(row=3, col=2) = mat[11]  → should be -1
    //   m(row=2, col=3) = mat[14]  → should be non-zero
    float m32 = m(mat, 3, 2);  // should be -1
    float m23 = m(mat, 2, 3);  // should be non-zero (the 2fn/(n-f) term)
    return (std::fabs(m32 - (-1.0f)) < eps) && (std::fabs(m23) > eps);
}

bool MatrixClassifier::is_orthographic_projection(const float* mat, float eps) {
    // Orthographic projection requirements (column-major):
    //  1. Last row [row=3] is [0,0,0,1]:  mat[3], mat[7], mat[11] ≈ 0; mat[15] ≈ 1
    //  2. Not a perspective matrix (m(3,2) ≠ -1)
    //  3. Not near-identity (at least one diagonal scale element ≠ 1), because
    //     identity would satisfy condition 1 trivially but has no projection meaning.
    float r30 = m(mat, 3, 0);   // mat[3]
    float r31 = m(mat, 3, 1);   // mat[7]
    float r32_val = m(mat, 3, 2);   // mat[11]
    float m33 = m(mat, 3, 3);   // mat[15]

    bool last_row_ok = (std::fabs(r30) < eps) &&
                       (std::fabs(r31) < eps) &&
                       (std::fabs(r32_val) < eps) &&
                       (std::fabs(m33 - 1.0f) < eps);
    if (!last_row_ok) return false;

    // Not perspective: m(row=3, col=2) should not be -1
    if (std::fabs(r32_val - (-1.0f)) < eps) return false;

    // Require at least one off-diagonal-or-non-unit element in the upper-left 3x3
    // to rule out identity and plain rigid transforms.
    // Ortho has scale ≠ 1 on diagonal (typically) OR non-zero translation.
    float sx = m(mat, 0, 0);  // mat[0]
    float sy = m(mat, 1, 1);  // mat[5]
    float sz = m(mat, 2, 2);  // mat[10]
    // Check off-diagonals of upper-left 3x3 are near zero (ortho has no rotation)
    float od01 = m(mat, 0, 1); float od10 = m(mat, 1, 0);
    float od02 = m(mat, 0, 2); float od20 = m(mat, 2, 0);
    float od12 = m(mat, 1, 2); float od21 = m(mat, 2, 1);
    bool diagonal_only = (std::fabs(od01) < eps) && (std::fabs(od10) < eps) &&
                         (std::fabs(od02) < eps) && (std::fabs(od20) < eps) &&
                         (std::fabs(od12) < eps) && (std::fabs(od21) < eps);
    if (!diagonal_only) return false;

    // Must have at least one scale ≠ 1 to distinguish from identity/rigid
    bool has_non_unit_scale = (std::fabs(sx - 1.0f) > eps) ||
                               (std::fabs(sy - 1.0f) > eps) ||
                               (std::fabs(sz - 1.0f) > eps);
    if (!has_non_unit_scale) {
        // Check translation column (col 3, rows 0-2): mat[12], mat[13], mat[14]
        float tx = m(mat, 0, 3);
        float ty = m(mat, 1, 3);
        float tz = m(mat, 2, 3);
        bool has_translation = (std::fabs(tx) > eps) ||
                                (std::fabs(ty) > eps) ||
                                (std::fabs(tz) > eps);
        if (!has_translation) return false;
    }

    return true;
}

// ---------------------------------------------------------------------------
// Pass 1: name-based classification
// ---------------------------------------------------------------------------

MatrixClassifier::Classification MatrixClassifier::classify_by_name(
    const std::string& name) {
    if (name.empty()) return {MatrixSemantic::Unknown, 0.0f};

    // Normal (check before Model to avoid "normalMatrix" → Model)
    if (name_contains(name, "normal") ||
        name_contains(name, "nmatrix") ||
        name_contains(name, "normalmat")) {
        return {MatrixSemantic::Normal, 0.8f};
    }
    // MVP (check before individual matrices to catch "transform"/"mvp")
    if (name_contains(name, "mvp") ||
        name_contains(name, "wvp")) {
        return {MatrixSemantic::MVP, 0.8f};
    }
    // Projection
    if (name_contains(name, "proj") ||
        name_contains(name, "p_matrix") ||
        name_contains(name, "uproj")) {
        return {MatrixSemantic::Projection, 0.8f};
    }
    // View
    if (name_contains(name, "view") ||
        name_contains(name, "camera") ||
        name_contains(name, "v_matrix") ||
        name_contains(name, "uview") ||
        name_contains(name, "worldtocamera")) {
        return {MatrixSemantic::View, 0.8f};
    }
    // Model
    if (name_contains(name, "model") ||
        name_contains(name, "world") ||
        name_contains(name, "m_matrix") ||
        name_contains(name, "umodel") ||
        name_contains(name, "objecttoworld")) {
        return {MatrixSemantic::Model, 0.8f};
    }
    // Generic transform keywords → MVP
    if (name_contains(name, "transform") ||
        name_contains(name, "matrix")) {
        return {MatrixSemantic::MVP, 0.8f};
    }

    return {MatrixSemantic::Unknown, 0.0f};
}

// ---------------------------------------------------------------------------
// Pass 2: structure-based classification
// ---------------------------------------------------------------------------

MatrixClassifier::Classification MatrixClassifier::classify_by_structure(
    const float* data) {
    if (data == nullptr) return {MatrixSemantic::Unknown, 0.0f};

    if (is_perspective_projection(data)) {
        return {MatrixSemantic::Projection, 0.5f};
    }
    if (is_orthographic_projection(data)) {
        return {MatrixSemantic::Projection, 0.5f};
    }
    if (is_orthonormal_3x3(data)) {
        // Could be model or view; ambiguous without a name hint.
        // Return Unknown at confidence 0.4 (below the 0.5 threshold that would
        // trigger structural-only promotion).
        return {MatrixSemantic::Unknown, 0.4f};
    }

    return {MatrixSemantic::Unknown, 0.0f};
}

// ---------------------------------------------------------------------------
// Public: classify(name, data)
// ---------------------------------------------------------------------------

MatrixClassifier::Classification MatrixClassifier::classify(
    const std::string& name, const float* data) const {

    Classification by_name = classify_by_name(name);
    Classification by_struct = classify_by_structure(data);

    bool have_name = (by_name.semantic != MatrixSemantic::Unknown);
    bool have_struct = (by_struct.semantic != MatrixSemantic::Unknown &&
                        by_struct.confidence >= 0.5f);

    if (!have_name && !have_struct) {
        // Return whichever has the higher (possibly zero) confidence
        if (by_name.confidence >= by_struct.confidence) return by_name;
        return by_struct;
    }

    if (have_name && !have_struct) {
        return {by_name.semantic, by_name.confidence};
    }

    if (!have_name && have_struct) {
        return {by_struct.semantic, by_struct.confidence};
    }

    // Both produced a result
    if (by_name.semantic == by_struct.semantic) {
        // Agree → high confidence
        return {by_name.semantic, 0.9f};
    } else {
        // Disagree → name wins at reduced confidence
        return {by_name.semantic, 0.6f};
    }
}

// ---------------------------------------------------------------------------
// Public: classify_frame(frame)
// ---------------------------------------------------------------------------

// ParamType value for mat4 — mirrors the protocol definition (GL_FLOAT_MAT4 = 0x8B5C = 35676)
static constexpr uint32_t kMat4Type = 0x8B5C;
static constexpr size_t kMat4Bytes = 16 * sizeof(float);

std::unordered_map<std::string, MatrixClassifier::Classification>
MatrixClassifier::classify_frame(const NormalizedFrame& frame) const {
    // Collect all draw calls
    auto all_dcs = frame.all_draw_calls();

    // For each mat4 param name, collect the distinct raw data blobs seen
    // (we compare byte-for-byte across draw calls to detect change)
    std::unordered_map<std::string, std::vector<std::vector<uint8_t>>> param_data;

    for (const auto& dc_ref : all_dcs) {
        const NormalizedDrawCall& dc = dc_ref.get();
        for (const auto& p : dc.params) {
            if (p.type == kMat4Type && p.data.size() == kMat4Bytes) {
                param_data[p.name].push_back(p.data);
            }
        }
    }

    std::unordered_map<std::string, Classification> result;

    for (const auto& [pname, blobs] : param_data) {
        // Use the first blob as reference data for structural analysis
        const float* mat_data = reinterpret_cast<const float*>(blobs[0].data());

        // Base classification via name + structure
        Classification base = classify(pname, mat_data);

        // Change-rate: does the value differ across draw calls?
        bool changes = false;
        for (size_t i = 1; i < blobs.size() && !changes; ++i) {
            if (blobs[i] != blobs[0]) changes = true;
        }

        Classification final_class = base;

        if (changes) {
            // Changes per draw-call → likely Model matrix
            if (base.semantic == MatrixSemantic::Unknown ||
                base.semantic == MatrixSemantic::MVP) {
                final_class = {MatrixSemantic::Model, 0.7f};
            } else if (base.semantic == MatrixSemantic::Model) {
                // Already model; boost confidence slightly
                final_class = {MatrixSemantic::Model,
                                std::min(base.confidence + 0.1f, 1.0f)};
            }
        } else if (blobs.size() > 1) {
            // Constant across all draw calls → likely View or Projection
            if (base.semantic == MatrixSemantic::Unknown) {
                // Structural analysis might help: pick View as a mild guess
                final_class = {MatrixSemantic::View, 0.5f};
            }
        }

        result[pname] = final_class;
    }

    return result;
}

}  // namespace gla
