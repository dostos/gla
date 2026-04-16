#include "src/core/semantic/scene_reconstructor.h"

namespace gla {

SceneInfo SceneReconstructor::reconstruct(const NormalizedFrame& frame) const {
    // Stub implementation: return minimal scene info
    // TODO(M3): Implement full scene reconstruction orchestration
    SceneInfo info;
    info.camera = camera_extractor_.extract(frame);
    info.objects = object_grouper_.group(frame);
    info.reconstruction_quality = "raw_only";
    return info;
}

}  // namespace gla
