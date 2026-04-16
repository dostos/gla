#pragma once
#include "src/core/normalize/normalized_types.h"
#include "src/core/store/raw_frame.h"

namespace gla {

class Normalizer {
public:
    // Convert a raw frame to normalized representation
    NormalizedFrame normalize(const gla::store::RawFrame& raw) const;
};

}  // namespace gla
