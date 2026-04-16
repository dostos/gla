#pragma once
#include <cstdint>
#include <vector>
#include "src/core/normalize/normalized_types.h"

namespace gla {

struct SceneObject {
    uint32_t id;
    std::vector<uint32_t> draw_call_ids;
    float world_transform[16];  // mat4 in column-major order
    float bbox_min[3], bbox_max[3];  // Axis-aligned bounding box
    bool visible;
    float confidence;
};

class ObjectGrouper {
public:
    /**
     * Group draw calls into logical scene objects.
     *
     * Analyzes draw call sequences, vertex data, and transform matrices
     * to identify coherent scene objects.
     *
     * @param frame The normalized frame to analyze.
     * @return Vector of reconstructed scene objects.
     */
    std::vector<SceneObject> group(const NormalizedFrame& frame) const;
};

}  // namespace gla
