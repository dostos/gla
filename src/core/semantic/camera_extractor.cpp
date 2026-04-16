#include "src/core/semantic/camera_extractor.h"

namespace gla {

std::optional<CameraInfo> CameraExtractor::extract(const NormalizedFrame& frame) const {
    // Stub implementation: return no camera info
    // TODO(M3): Implement camera extraction from projection matrices
    return std::nullopt;
}

}  // namespace gla
