#pragma once
#include "src/core/normalize/normalized_types.h"
#include "src/core/store/raw_frame.h"

namespace gla::normalize {

class Normalizer {
public:
    Normalizer() = default;
    ~Normalizer() = default;
    NormalizedDrawCall normalize(const gla::store::RawFrame &f);
};

} // namespace gla::normalize
