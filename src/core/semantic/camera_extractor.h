#pragma once
#include <optional>
#include "src/core/normalize/normalized_types.h"

namespace gla {

struct CameraInfo {
    float position[3];
    float forward[3];
    float up[3];
    float fov_y_degrees;
    float aspect;
    float near_plane, far_plane;
    bool is_perspective;
    float confidence;
};

class CameraExtractor {
public:
    /**
     * Extract camera information from a normalized frame.
     *
     * Analyzes projection matrices and camera parameters to reconstruct
     * camera position, orientation, and projection settings.
     *
     * @param frame The normalized frame to analyze.
     * @return Optional CameraInfo if extraction was successful; std::nullopt otherwise.
     */
    std::optional<CameraInfo> extract(const NormalizedFrame& frame) const;
};

}  // namespace gla
