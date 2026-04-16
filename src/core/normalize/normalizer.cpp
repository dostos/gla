// Normalizer — stub
#include "src/core/normalize/normalizer.h"

namespace gla::normalize {

NormalizedDrawCall Normalizer::normalize(const gla::store::RawFrame &f) {
    (void)f;
    return NormalizedDrawCall{0, 0};
}

} // namespace gla::normalize
