#pragma once
#include <string>
#include <optional>
#include <vector>
#include "src/core/semantic/camera_extractor.h"
#include "src/core/semantic/object_grouper.h"
#include "src/core/normalize/normalized_types.h"

namespace gla {

struct SceneInfo {
    std::optional<CameraInfo> camera;
    std::vector<SceneObject> objects;
    std::string reconstruction_quality;  // "full", "partial", "raw_only"
};

class SceneReconstructor {
public:
    /**
     * Reconstruct complete scene information from a normalized frame.
     *
     * Orchestrates camera extraction and object grouping to build a complete
     * semantic scene representation from raw graphics data.
     *
     * @param frame The normalized frame to reconstruct from.
     * @return SceneInfo containing camera and object information.
     */
    SceneInfo reconstruct(const NormalizedFrame& frame) const;

private:
    CameraExtractor camera_extractor_;
    ObjectGrouper object_grouper_;
};

}  // namespace gla
